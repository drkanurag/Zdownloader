import asyncio
import uuid
import re
from urllib.parse import urlparse, unquote
from typing import Optional, List, Dict, Any
import httpx
import yt_dlp

from app.domain.models import AnalyzedLink, FormatOption
from app.dsa.lru_cache import LRUCacheWithTTL
from app.dsa.trie import DomainRadixTrie
from app.core.security import validate_url_security
from app.core.circuit_breaker import CircuitBreaker
from app.utils import format_bytes, format_seconds, get_ffmpeg_path

DIRECT_EXTENSIONS = {
    ".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".ts",
    ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".pdf", ".iso", ".exe"
}

class InspectionService:
    """
    Link Inspection & Extraction Microservice.
    
    Features:
      - SSRF security validation
      - LRU Cache with TTL for rapid O(1) cached metadata resolution
      - Radix Trie for domain categorization
      - Circuit Breaker resilience
    """
    def __init__(self):
        self.cache: LRUCacheWithTTL[str, AnalyzedLink] = LRUCacheWithTTL(capacity=200, default_ttl_seconds=600.0)
        self.circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=20.0)
        self.domain_trie = DomainRadixTrie()
        self._init_domain_trie()

    def _init_domain_trie(self):
        # Preload common platforms for rapid O(L) classification
        self.domain_trie.insert("youtube.com", "YouTube")
        self.domain_trie.insert("youtu.be", "YouTube")
        self.domain_trie.insert("vimeo.com", "Vimeo")
        self.domain_trie.insert("twitter.com", "X / Twitter")
        self.domain_trie.insert("x.com", "X / Twitter")
        self.domain_trie.insert("tiktok.com", "TikTok")
        self.domain_trie.insert("reddit.com", "Reddit")
        self.domain_trie.insert("instagram.com", "Instagram")
        self.domain_trie.insert("facebook.com", "Facebook")
        self.domain_trie.insert("twitch.tv", "Twitch")
        self.domain_trie.insert("soundcloud.com", "SoundCloud")

    def is_direct_file_url(self, url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.lower()
        return any(path.endswith(ext) for ext in DIRECT_EXTENSIONS)

    async def probe_direct_file(self, url: str) -> Optional[AnalyzedLink]:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8.0, verify=False) as client:
                try:
                    resp = await client.head(url)
                except Exception:
                    resp = await client.get(url, headers={"Range": "bytes=0-0"})

                if resp.status_code not in (200, 206):
                    return None

                content_type = resp.headers.get("content-type", "").lower()
                content_length = resp.headers.get("content-length")
                content_disposition = resp.headers.get("content-disposition", "")

                if "text/html" in content_type:
                    return None

                filename = "downloaded_file"
                if "filename=" in content_disposition:
                    match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', content_disposition, re.IGNORECASE)
                    if match:
                        filename = unquote(match.group(1))
                else:
                    parsed = urlparse(str(resp.url))
                    base = unquote(parsed.path.split("/")[-1])
                    if base:
                        filename = base

                # Extract size from Content-Range or Content-Length
                size_bytes = None
                content_range = resp.headers.get("content-range", "")
                if "/" in content_range:
                    total_part = content_range.split("/")[-1].strip()
                    if total_part.isdigit():
                        size_bytes = int(total_part)

                if size_bytes is None and content_length and content_length.isdigit():
                    size_bytes = int(content_length)

                ext = filename.split(".")[-1].lower() if "." in filename else "bin"

                format_opt = FormatOption(
                    format_id="direct",
                    label=f"Original File (.{ext.upper()})",
                    ext=ext,
                    filesize=size_bytes,
                    filesize_str=format_bytes(size_bytes),
                    is_audio_only=False,
                    needs_merge=False
                )

                return AnalyzedLink(
                    id=str(uuid.uuid4()),
                    url=url,
                    status="direct_file",
                    title=filename,
                    platform="Direct File",
                    formats=[format_opt],
                    selected_format_id="direct"
                )
        except Exception:
            return None

    def _extract_ytdlp(self, url: str) -> Dict[str, Any]:
        ffmpeg_exe = get_ffmpeg_path()
        ydl_opts: Dict[str, Any] = {
            "extract_flat": False,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 12,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web"]
                }
            },
        }
        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return ydl.sanitize_info(info)

    def _build_format_options(self, info: Dict[str, Any]) -> List[FormatOption]:
        formats = info.get("formats", [])
        options: List[FormatOption] = []
        available_heights = set()
        best_size = None

        for f in formats:
            h = f.get("height")
            if h and isinstance(h, int):
                available_heights.add(h)
            if f.get("filesize"):
                best_size = max(best_size or 0, f["filesize"])

        max_h = max(available_heights) if available_heights else None
        max_label = f"Highest Quality MP4 ({max_h}p)" if max_h else "Highest Quality (MP4 Video)"

        options.append(FormatOption(
            format_id="bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best",
            label=max_label,
            height=max_h,
            ext="mp4",
            filesize=best_size,
            filesize_str=format_bytes(best_size) if best_size else "Original MP4 stream",
            needs_merge=True
        ))

        target_resolutions = [
            (2160, "4K (2160p)"),
            (1440, "2K (1440p)"),
            (1080, "1080p (Full HD)"),
            (720, "720p (HD)"),
            (480, "480p (SD)"),
            (360, "360p")
        ]

        for height_thresh, label in target_resolutions:
            if any(h == height_thresh for h in available_heights):
                fmt_id = f"bestvideo[height<={height_thresh}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={height_thresh}]+bestaudio/best[height<={height_thresh}][ext=mp4]/best"
                options.append(FormatOption(
                    format_id=fmt_id,
                    label=f"{label} (MP4 Video)",
                    height=height_thresh,
                    ext="mp4",
                    needs_merge=True
                ))

        options.append(FormatOption(
            format_id="bestaudio/best",
            label="Audio Only (High Quality MP3)",
            ext="mp3",
            is_audio_only=True,
            needs_merge=False
        ))
        return options

    async def analyze(self, url: str) -> AnalyzedLink:
        url = url.strip()
        link_id = str(uuid.uuid4())

        # 1. Check LRU Cache
        cached = await self.cache.get(url)
        if cached:
            return cached

        # 2. SSRF Security Validation
        is_safe, sec_reason = validate_url_security(url)
        if not is_safe:
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="unsupported",
                title="Security Policy Blocked",
                error_message=f"SSRF Protection: {sec_reason}"
            )

        # 3. Direct File Check
        if self.is_direct_file_url(url):
            direct_res = await self.probe_direct_file(url)
            if direct_res:
                await self.cache.put(url, direct_res)
                return direct_res

        # 4. Radix Trie Platform Match
        domain = urlparse(url).hostname or ""
        platform_name = self.domain_trie.match_subdomain(domain) or "Video Platform"

        # 5. Extract with yt-dlp via Circuit Breaker
        try:
            info = await self.circuit_breaker.execute(
                asyncio.to_thread, self._extract_ytdlp, url
            )

            if not info:
                return AnalyzedLink(
                    id=link_id,
                    url=url,
                    status="unsupported",
                    title="No media found",
                    error_message="Could not locate downloadable media streams."
                )

            title = info.get("title") or "Untitled Video"
            duration = info.get("duration")
            duration_str = format_seconds(duration) if duration else None
            thumbnail = info.get("thumbnail")
            uploader = info.get("uploader") or info.get("channel") or info.get("creator")
            platform = info.get("extractor_key") or platform_name

            formats = self._build_format_options(info)
            default_fmt = formats[0].format_id if formats else "best"

            result = AnalyzedLink(
                id=link_id,
                url=url,
                status="supported",
                title=title,
                duration=duration,
                duration_str=duration_str,
                thumbnail=thumbnail,
                uploader=uploader,
                platform=platform,
                formats=formats,
                selected_format_id=default_fmt
            )
            await self.cache.put(url, result)
            return result

        except yt_dlp.utils.DownloadError as e:
            err_msg = str(e)
            if "DRM" in err_msg or "encrypted" in err_msg.lower() or "widevine" in err_msg.lower():
                return AnalyzedLink(
                    id=link_id,
                    url=url,
                    status="drm_protected",
                    title="DRM Protected Content",
                    error_message="This media is protected by DRM encryption and cannot be downloaded."
                )
            elif "login" in err_msg.lower() or "sign in" in err_msg.lower() or "private" in err_msg.lower():
                return AnalyzedLink(
                    id=link_id,
                    url=url,
                    status="unsupported",
                    title="Authentication Required",
                    error_message="This media is private or requires user login credentials."
                )
            else:
                direct_fallback = await self.probe_direct_file(url)
                if direct_fallback:
                    await self.cache.put(url, direct_fallback)
                    return direct_fallback

                clean_err = err_msg.replace("ERROR: ", "").split(";")[0].strip()
                return AnalyzedLink(
                    id=link_id,
                    url=url,
                    status="unsupported",
                    title="Unsupported or Inaccessible Link",
                    error_message=clean_err or "Website is not supported."
                )
        except Exception as e:
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="error",
                title="Analysis Failed",
                error_message=str(e)
            )

inspection_service = InspectionService()

