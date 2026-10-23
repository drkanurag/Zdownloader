import os
import re
import time
import asyncio
from typing import Callable, Optional, Dict, Any
from urllib.parse import urlparse, unquote
import httpx
import aiofiles
import yt_dlp

from app.domain.models import DownloadJob, JobStatus
from app.domain.events import JobProgressEvent, JobCompletedEvent, JobFailedEvent
from app.domain.exceptions import (
    DownloadCancelledException,
    DownloadPausedException,
    InsufficientDiskSpaceException
)
from app.dsa.sliding_window import SlidingWindowSpeedEstimator
from app.dsa.token_bucket import TokenBucketRateLimiter
from app.core.event_bus import event_bus
from app.services.storage_service import storage_service
from app.utils import (
    get_ffmpeg_path,
    format_bytes,
    format_speed,
    format_seconds,
    sanitize_filename
)

class DownloadService:
    """
    Download Engine & Stream Processing Microservice.
    
    Features:
      - Sliding Window Moving Average for smooth speed calculation and stable ETA
      - Token Bucket bandwidth control
      - Event-driven notifications via EventBus
      - Safe transactional file streaming (.zpart -> final)
      - Lossless audio/video stream remuxing via FFmpeg
    """
    def __init__(self, bandwidth_limit_bytes_sec: Optional[float] = None):
        self.rate_limiter: Optional[TokenBucketRateLimiter] = None
        if bandwidth_limit_bytes_sec:
            self.rate_limiter = TokenBucketRateLimiter(
                capacity=bandwidth_limit_bytes_sec * 2,
                refill_rate=bandwidth_limit_bytes_sec
            )

    async def download_direct(
        self,
        job: DownloadJob,
        check_cancelled: Callable[[], bool],
        check_paused: Optional[Callable[[], bool]] = None
    ) -> str:
        """Download direct file using chunked HTTP streaming with HTTP Range resume and disk capacity validation."""
        target_dir = job.download_dir
        os.makedirs(target_dir, exist_ok=True)
        speed_estimator = SlidingWindowSpeedEstimator(window_seconds=2.0)

        final_filepath = job.target_filepath
        if not final_filepath:
            parsed = urlparse(job.url)
            base = unquote(parsed.path.split("/")[-1])
            prelim_name = sanitize_filename(base if base else f"download_{job.id[:8]}")
            final_filepath = os.path.join(target_dir, prelim_name)

        part_filepath = final_filepath + ".zpart"
        existing_bytes = 0
        if os.path.exists(part_filepath):
            existing_bytes = os.path.getsize(part_filepath)

        headers = {"User-Agent": "Zdownloader/2.0"}
        if existing_bytes > 0:
            headers["Range"] = f"bytes={existing_bytes}-"

        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, verify=False) as client:
            async with client.stream("GET", job.url, headers=headers) as response:
                if response.status_code == 416 and existing_bytes > 0:
                    if job.total_bytes and existing_bytes >= job.total_bytes:
                        if os.path.exists(part_filepath):
                            os.replace(part_filepath, final_filepath)
                        job.downloaded_bytes = existing_bytes
                        job.progress_percent = 100.0
                        job.status = JobStatus.COMPLETED
                        return final_filepath
                    existing_bytes = 0
                    if os.path.exists(part_filepath):
                        os.remove(part_filepath)

                response.raise_for_status()

                content_disposition = response.headers.get("content-disposition", "")
                filename = ""
                if "filename=" in content_disposition:
                    match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', content_disposition, re.IGNORECASE)
                    if match:
                        filename = unquote(match.group(1))

                if not filename and not job.filename:
                    parsed = urlparse(str(response.url))
                    base = unquote(parsed.path.split("/")[-1])
                    filename = base if base else f"download_{job.id[:8]}"

                if filename:
                    filename = sanitize_filename(filename)
                    job.filename = filename
                    final_filepath = os.path.join(target_dir, filename)
                    part_filepath = final_filepath + ".zpart"

                job.target_filepath = final_filepath

                content_range = response.headers.get("content-range")
                if content_range and "/" in content_range:
                    try:
                        total_bytes = int(content_range.split("/")[-1])
                    except Exception:
                        total_bytes = None
                else:
                    content_length = response.headers.get("content-length")
                    total_bytes = int(content_length) if content_length and content_length.isdigit() else None
                    if response.status_code == 206 and total_bytes:
                        total_bytes += existing_bytes

                job.total_bytes = total_bytes

                bytes_needed = (total_bytes - existing_bytes) if (total_bytes and total_bytes > existing_bytes) else None
                if not storage_service.has_sufficient_space(bytes_needed):
                    raise InsufficientDiskSpaceException(
                        f"Insufficient disk space in {target_dir}. Free: {storage_service.get_disk_usage().get('free_str', 'N/A')}"
                    )

                if response.status_code == 206 and existing_bytes > 0:
                    file_mode = "ab"
                    downloaded = existing_bytes
                else:
                    file_mode = "wb"
                    downloaded = 0

                last_notify_time = time.time()

                try:
                    async with aiofiles.open(part_filepath, file_mode) as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            if check_paused and check_paused():
                                raise DownloadPausedException("Download paused by user.")
                            if check_cancelled():
                                raise DownloadCancelledException("Download cancelled by user.")

                            if self.rate_limiter:
                                await self.rate_limiter.acquire(len(chunk))

                            await f.write(chunk)
                            downloaded += len(chunk)

                            speed_estimator.record(downloaded)
                            now = time.time()

                            if now - last_notify_time >= 0.15:
                                speed = speed_estimator.get_speed()
                                eta = speed_estimator.estimate_eta(total_bytes)

                                job.downloaded_bytes = downloaded
                                job.speed_bytes_sec = speed
                                job.speed_str = format_speed(speed)
                                job.eta_seconds = eta
                                job.eta_str = format_seconds(eta) if eta is not None else "--:--"

                                if total_bytes and total_bytes > 0:
                                    job.progress_percent = round((downloaded / total_bytes) * 100, 1)

                                last_notify_time = now
                                await event_bus.publish(JobProgressEvent(
                                    event_id=f"prog-{job.id}-{int(now*1000)}",
                                    event_type="job_progress",
                                    job_id=job.id,
                                    status=job.status.value,
                                    progress_percent=job.progress_percent,
                                    downloaded_bytes=job.downloaded_bytes,
                                    total_bytes=job.total_bytes,
                                    speed_str=job.speed_str,
                                    eta_str=job.eta_str
                                ))

                    if os.path.exists(part_filepath):
                        if os.path.exists(final_filepath):
                            base_n, ext_n = os.path.splitext(final_filepath)
                            cnt = 1
                            while os.path.exists(f"{base_n} ({cnt}){ext_n}"):
                                cnt += 1
                            final_filepath = f"{base_n} ({cnt}){ext_n}"
                        os.replace(part_filepath, final_filepath)

                    job.downloaded_bytes = downloaded
                    job.progress_percent = 100.0
                    job.status = JobStatus.COMPLETED
                    job.target_filepath = final_filepath
                    job.filename = os.path.basename(final_filepath)

                    await event_bus.publish(JobCompletedEvent(
                        event_id=f"done-{job.id}",
                        event_type="job_completed",
                        job_id=job.id,
                        filepath=final_filepath,
                        filename=job.filename,
                        total_bytes=downloaded
                    ))
                    return final_filepath

                except DownloadPausedException:
                    job.status = JobStatus.PAUSED
                    job.speed_str = "Paused"
                    job.eta_str = ""
                    raise
                except DownloadCancelledException:
                    if os.path.exists(part_filepath):
                        try:
                            os.remove(part_filepath)
                        except Exception:
                            pass
                    raise
                except Exception as e:
                    raise e

    def _download_ytdlp_sync(
        self,
        job: DownloadJob,
        loop: asyncio.AbstractEventLoop,
        check_cancelled: Callable[[], bool],
        check_paused: Optional[Callable[[], bool]] = None
    ) -> str:
        """Run yt-dlp synchronously with hooks, sliding window speed estimation, and disk space validation."""
        target_dir = job.download_dir
        os.makedirs(target_dir, exist_ok=True)
        if not storage_service.has_sufficient_space():
            raise InsufficientDiskSpaceException(f"Insufficient disk space in download directory: {storage_service.base_dir}")

        ffmpeg_exe = get_ffmpeg_path()
        speed_estimator = SlidingWindowSpeedEstimator(window_seconds=2.0)

        outtmpl = os.path.join(target_dir, "%(title)s [%(id)s].%(ext)s")
        final_file = [None]
        last_update = [0.0]

        def ytdlp_progress_hook(d: Dict[str, Any]):
            if check_paused and check_paused():
                raise DownloadPausedException("Download paused by user.")
            if check_cancelled():
                raise DownloadCancelledException("Download cancelled by user.")

            status = d.get("status")
            now = time.time()

            if status == "downloading":
                job.status = JobStatus.DOWNLOADING
                downloaded = d.get("downloaded_bytes", 0)
                raw_total = d.get("total_bytes") or d.get("total_bytes_estimate")
                speed_estimator.record(downloaded)

                job.downloaded_bytes = downloaded
                if raw_total:
                    total = int(raw_total)
                    job.total_bytes = total
                    job.progress_percent = round((downloaded / total) * 100.0, 1)

                speed = speed_estimator.get_speed() or d.get("speed")
                eta = speed_estimator.estimate_eta(raw_total) if raw_total else d.get("eta")

                if speed:
                    job.speed_bytes_sec = speed
                    job.speed_str = format_speed(speed)
                if eta is not None:
                    job.eta_seconds = int(eta)
                    job.eta_str = format_seconds(eta)

                filename = d.get("filename")
                if filename:
                    job.filename = os.path.basename(filename)
                    job.target_filepath = filename
                    final_file[0] = filename

                if now - last_update[0] >= 0.15:
                    last_update[0] = now
                    asyncio.run_coroutine_threadsafe(
                        event_bus.publish(JobProgressEvent(
                            event_id=f"prog-{job.id}-{int(now*1000)}",
                            event_type="job_progress",
                            job_id=job.id,
                            status=job.status.value,
                            progress_percent=job.progress_percent,
                            downloaded_bytes=job.downloaded_bytes,
                            total_bytes=job.total_bytes,
                            speed_str=job.speed_str,
                            eta_str=job.eta_str
                        )),
                        loop
                    )

            elif status == "finished":
                job.status = JobStatus.MERGING
                filename = d.get("filename")
                if filename:
                    job.filename = os.path.basename(filename)
                    job.target_filepath = filename
                    final_file[0] = filename

                asyncio.run_coroutine_threadsafe(
                    event_bus.publish(JobProgressEvent(
                        event_id=f"merge-{job.id}",
                        event_type="job_progress",
                        job_id=job.id,
                        status=JobStatus.MERGING.value,
                        progress_percent=99.0,
                        downloaded_bytes=job.downloaded_bytes,
                        total_bytes=job.total_bytes,
                        speed_str="Merging streams...",
                        eta_str=""
                    )),
                    loop
                )

        def postprocessor_hook(d: Dict[str, Any]):
            if check_paused and check_paused():
                raise DownloadPausedException("Download paused by user.")
            if check_cancelled():
                raise DownloadCancelledException("Download cancelled by user.")
            if d.get("status") == "started":
                job.status = JobStatus.MERGING
            elif d.get("status") == "finished":
                filepath = d.get("info_dict", {}).get("_filename") or d.get("info_dict", {}).get("filepath")
                if filepath and os.path.exists(filepath):
                    final_file[0] = filepath
                    job.filename = os.path.basename(filepath)
                    job.target_filepath = filepath

        ydl_opts: Dict[str, Any] = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "restrictfilenames": True,
            "windowsfilenames": True,
            "progress_hooks": [ytdlp_progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "nocheckcertificate": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "tv", "mweb"]
                }
            },
        }

        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe

        format_id = job.format_id or "best"
        is_audio_only = (
            format_id == "bestaudio/best"
            or format_id == "audio_only"
            or (format_id.startswith("bestaudio") and "bestvideo" not in format_id and "+bestaudio" not in format_id)
        )

        if is_audio_only:
            ydl_opts["format"] = "bestaudio/best"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }]
        elif format_id == "best" or format_id == "bestvideo+bestaudio/best":
            ydl_opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best"
            ydl_opts["merge_output_format"] = "mp4"
        elif "bestvideo" in format_id:
            if "[height<=" in format_id:
                h_match = re.search(r'height<=(\d+)', format_id)
                if h_match:
                    h = h_match.group(1)
                    ydl_opts["format"] = f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}][ext=mp4]/best[height<={h}]/best"
                else:
                    ydl_opts["format"] = format_id
            else:
                ydl_opts["format"] = f"{format_id}[ext=mp4]+bestaudio[ext=m4a]/{format_id}+bestaudio/{format_id}"
            ydl_opts["merge_output_format"] = "mp4"
        else:
            ydl_opts["format"] = f"{format_id}+bestaudio[ext=m4a]/{format_id}+bestaudio/{format_id}"
            ydl_opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(job.url, download=True)
            if not final_file[0]:
                calc_filename = ydl.prepare_filename(info)
                if is_audio_only:
                    calc_filename = os.path.splitext(calc_filename)[0] + ".mp3"
                else:
                    calc_filename = os.path.splitext(calc_filename)[0] + ".mp4"
                final_file[0] = calc_filename

        if final_file[0] and not os.path.exists(final_file[0]):
            base_cand = re.sub(r'\.f\d+$', '', os.path.splitext(final_file[0])[0])
            for ext_cand in [".mp4", ".mkv", ".webm", ".mp3", ".m4a"]:
                cand_path = base_cand + ext_cand
                if os.path.exists(cand_path):
                    final_file[0] = cand_path
                    break

        if not final_file[0] or not os.path.exists(final_file[0]):
            try:
                candidates = [
                    os.path.join(target_dir, f)
                    for f in os.listdir(target_dir)
                    if os.path.isfile(os.path.join(target_dir, f)) and not f.endswith((".part", ".ytdl", ".zpart"))
                ]
                if candidates:
                    candidates.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                    final_file[0] = candidates[0]
            except Exception:
                pass

        result_path = final_file[0] or ""
        if result_path and os.path.exists(result_path):
            job.filename = os.path.basename(result_path)
            job.target_filepath = result_path
            job.progress_percent = 100.0
            job.status = JobStatus.COMPLETED
            asyncio.run_coroutine_threadsafe(
                event_bus.publish(JobCompletedEvent(
                    event_id=f"done-{job.id}",
                    event_type="job_completed",
                    job_id=job.id,
                    filepath=result_path,
                    filename=job.filename,
                    total_bytes=os.path.getsize(result_path)
                )),
                loop
            )
        return result_path

    async def download_ytdlp(
        self,
        job: DownloadJob,
        check_cancelled: Callable[[], bool],
        check_paused: Optional[Callable[[], bool]] = None
    ) -> str:
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(self._download_ytdlp_sync, job, loop, check_cancelled, check_paused)

download_service = DownloadService()

