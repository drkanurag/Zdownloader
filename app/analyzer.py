import asyncio
import uuid
import re
from urllib.parse import urlparse, unquote
from typing import Optional, List, Dict, Any
import httpx
import yt_dlp

from app.models import AnalyzedLink, FormatOption
from app.utils import format_bytes, format_seconds, get_ffmpeg_path

DIRECT_EXTENSIONS = {
    # Video
    ".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".ts",
    # Audio
    ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav",
    # Direct archive / documents
    ".zip", ".rar", ".7z", ".tar", ".gz", ".pdf", ".iso", ".exe"
}

def is_direct_file_url(url: str) -> bool:
    """Check if the URL path ends with a known direct file extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(path.endswith(ext) for ext in DIRECT_EXTENSIONS)

async def probe_direct_file(url: str) -> Optional[AnalyzedLink]:
    """Probe a potential direct file URL with a lightweight HTTP HEAD or streaming GET."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, verify=False) as client:
            try:
                resp = await client.head(url)
            except Exception:
                # Some servers disallow HEAD, try GET with range header to fetch just 1 byte
                resp = await client.get(url, headers={"Range": "bytes=0-0"})

            # Ensure response was successful (200 OK or 206 Partial Content)
            if resp.status_code not in (200, 206):
                return None

            content_type = resp.headers.get("content-type", "").lower()
            content_length = resp.headers.get("content-length")
            content_disposition = resp.headers.get("content-disposition", "")

            # If response looks like an HTML page, it's likely a web page, not a direct file
            if "text/html" in content_type:
                return None

            # Extract filename from Content-Disposition or URL path
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

            # Determine file size (from Content-Range or Content-Length)
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

def _extract_with_ytdlp(url: str) -> Dict[str, Any]:
    """Synchronous extraction using yt-dlp."""
    ffmpeg_exe = get_ffmpeg_path()
    ydl_opts: Dict[str, Any] = {
        "extract_flat": False,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 15,
    }
    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return ydl.sanitize_info(info)

def _build_format_options(info: Dict[str, Any]) -> List[FormatOption]:
    """Parse yt-dlp formats and build clean, user-friendly resolution options."""
    formats = info.get("formats", [])
    has_ffmpeg = get_ffmpeg_path() is not None

    # Always provide Highest Original Quality as the first and default option
    options: List[FormatOption] = []
    
    # Check max resolution in formats
    available_heights = set()
    best_size = None
    for f in formats:
        h = f.get("height")
        if h and isinstance(h, int):
            available_heights.add(h)
        if f.get("filesize"):
            best_size = max(best_size or 0, f["filesize"])

    max_h = max(available_heights) if available_heights else None
    max_label = f"Highest Quality ({max_h}p)" if max_h else "Highest Available Quality"

    options.append(FormatOption(
        format_id="bestvideo+bestaudio/best",
        label=max_label,
        height=max_h,
        ext="mp4",
        filesize=best_size,
        filesize_str=format_bytes(best_size) if best_size else "Original stream",
        needs_merge=True
    ))

    # Standard resolutions to look for
    target_resolutions = [
        (2160, "4K (2160p)"),
        (1440, "2K (1440p)"),
        (1080, "1080p (Full HD)"),
        (720, "720p (HD)"),
        (480, "480p (SD)"),
        (360, "360p")
    ]

    for height_thresh, label in target_resolutions:
        matching = [h for h in available_heights if h == height_thresh]
        if matching:
            # Build format selector for this specific resolution
            fmt_id = f"bestvideo[height<={height_thresh}]+bestaudio/best[height<={height_thresh}]/best"
            options.append(FormatOption(
                format_id=fmt_id,
                label=label,
                height=height_thresh,
                ext="mp4",
                needs_merge=True
            ))

    # Audio only option
    options.append(FormatOption(
        format_id="bestaudio/best",
        label="Audio Only (High Quality MP3/M4A)",
        ext="mp3",
        is_audio_only=True,
        needs_merge=False
    ))

    return options

async def analyze_url(url: str) -> AnalyzedLink:
    """Analyze a single URL and return metadata, available formats, and platform details."""
    link_id = str(uuid.uuid4())
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return AnalyzedLink(
            id=link_id,
            url=url,
            status="unsupported",
            title="Invalid URL",
            error_message="URL must start with http:// or https://"
        )

    # 1. First probe for direct downloadable media file
    if is_direct_file_url(url):
        direct_info = await probe_direct_file(url)
        if direct_info:
            return direct_info

    # 2. Extract using yt-dlp in thread pool
    try:
        info = await asyncio.to_thread(_extract_with_ytdlp, url)
        if not info:
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="unsupported",
                title="No media found",
                error_message="Could not locate downloadable media on this page."
            )

        title = info.get("title") or "Untitled Video"
        duration = info.get("duration")
        duration_str = format_seconds(duration) if duration else None
        thumbnail = info.get("thumbnail")
        uploader = info.get("uploader") or info.get("channel") or info.get("creator")
        platform = info.get("extractor_key") or info.get("extractor") or "Video Platform"

        formats = _build_format_options(info)
        default_fmt = formats[0].format_id if formats else "best"

        return AnalyzedLink(
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

    except yt_dlp.utils.DownloadError as e:
        err_msg = str(e)
        if "DRM" in err_msg or "encrypted" in err_msg.lower() or "widevine" in err_msg.lower():
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="drm_protected",
                title="DRM Protected Content",
                error_message="This video is protected by Digital Rights Management (DRM) and cannot be downloaded."
            )
        elif "login" in err_msg.lower() or "sign in" in err_msg.lower() or "private" in err_msg.lower():
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="unsupported",
                title="Authentication Required",
                error_message="This content is private or requires account sign-in."
            )
        else:
            # Check if direct file probe fallback works
            direct_fallback = await probe_direct_file(url)
            if direct_fallback:
                return direct_fallback

            # Friendly clean error
            clean_err = err_msg.replace("ERROR: ", "").split(";")[0].strip()
            return AnalyzedLink(
                id=link_id,
                url=url,
                status="unsupported",
                title="Unsupported or Inaccessible Link",
                error_message=clean_err or "Website is not supported or link is invalid."
            )
    except Exception as e:
        return AnalyzedLink(
            id=link_id,
            url=url,
            status="error",
            title="Analysis Failed",
            error_message=f"Error analyzing link: {str(e)}"
        )
