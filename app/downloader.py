import os
import time
import asyncio
from typing import Callable, Optional, Dict, Any
from urllib.parse import urlparse, unquote
import httpx
import aiofiles
import yt_dlp

from app.models import DownloadJob
from app.utils import (
    get_ffmpeg_path,
    format_bytes,
    format_speed,
    format_seconds,
    sanitize_filename
)

class DownloadCancelledException(Exception):
    """Raised when a download job is cancelled by the user."""
    pass

async def download_direct_file(
    job: DownloadJob,
    on_progress: Callable[[DownloadJob], Any],
    check_cancelled: Callable[[], bool]
) -> str:
    """Download a direct file using streaming HTTP with progress tracking and cancellation."""
    target_dir = job.download_dir
    os.makedirs(target_dir, exist_ok=True)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, verify=False) as client:
        async with client.stream("GET", job.url) as response:
            response.raise_for_status()

            # Determine filename
            content_disposition = response.headers.get("content-disposition", "")
            filename = ""
            if "filename=" in content_disposition:
                import re
                match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', content_disposition, re.IGNORECASE)
                if match:
                    filename = unquote(match.group(1))

            if not filename:
                parsed = urlparse(str(response.url))
                base = unquote(parsed.path.split("/")[-1])
                filename = base if base else f"download_{job.id[:8]}"

            filename = sanitize_filename(filename)
            job.filename = filename

            content_length = response.headers.get("content-length")
            total_bytes = int(content_length) if content_length and content_length.isdigit() else None
            job.total_bytes = total_bytes

            final_filepath = os.path.join(target_dir, filename)
            # If file already exists, generate a unique name
            base_name, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(final_filepath):
                final_filepath = os.path.join(target_dir, f"{base_name} ({counter}){ext}")
                counter += 1

            part_filepath = final_filepath + ".zpart"
            job.target_filepath = final_filepath

            downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            last_bytes = 0

            try:
                async with aiofiles.open(part_filepath, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        if check_cancelled():
                            raise DownloadCancelledException("Download cancelled by user.")

                        await f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()

                        # Update progress every ~150ms
                        if now - last_update_time >= 0.15:
                            elapsed = now - last_update_time
                            bytes_delta = downloaded - last_bytes
                            speed = bytes_delta / elapsed if elapsed > 0 else 0
                            eta = (total_bytes - downloaded) / speed if (total_bytes and speed > 0) else None

                            job.downloaded_bytes = downloaded
                            job.speed_bytes_sec = speed
                            job.speed_str = format_speed(speed)
                            job.eta_seconds = int(eta) if eta else None
                            job.eta_str = format_seconds(eta) if eta else "--:--"

                            if total_bytes and total_bytes > 0:
                                job.progress_percent = round((downloaded / total_bytes) * 100, 1)
                            else:
                                job.progress_percent = 0.0

                            last_update_time = now
                            last_bytes = downloaded
                            await on_progress(job)

                # Move part file to final file
                if os.path.exists(part_filepath):
                    os.replace(part_filepath, final_filepath)

                job.downloaded_bytes = downloaded
                job.progress_percent = 100.0
                job.speed_str = "-- KB/s"
                job.eta_str = "Completed"
                job.filename = os.path.basename(final_filepath)
                job.target_filepath = final_filepath
                await on_progress(job)
                return final_filepath

            except DownloadCancelledException:
                if os.path.exists(part_filepath):
                    try:
                        os.remove(part_filepath)
                    except Exception:
                        pass
                raise
            except Exception as e:
                if os.path.exists(part_filepath):
                    try:
                        os.remove(part_filepath)
                    except Exception:
                        pass
                raise e

def _download_ytdlp_sync(
    job: DownloadJob,
    on_progress_sync: Callable[[DownloadJob], Any],
    check_cancelled: Callable[[], bool]
) -> str:
    """Synchronously run yt-dlp with progress hooks."""
    target_dir = job.download_dir
    os.makedirs(target_dir, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_path()

    outtmpl = os.path.join(target_dir, "%(title)s [%(id)s].%(ext)s")

    last_update = [0.0]
    final_file = [None]

    def ytdlp_progress_hook(d: Dict[str, Any]):
        if check_cancelled():
            raise DownloadCancelledException("Download cancelled by user.")

        status = d.get("status")
        now = time.time()

        if status == "downloading":
            job.status = "downloading"
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed = d.get("speed")
            eta = d.get("eta")

            job.downloaded_bytes = downloaded
            if total:
                job.total_bytes = total
                job.progress_percent = round((downloaded / total) * 100.0, 1)

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

            # Throttle UI progress callbacks
            if now - last_update[0] >= 0.15:
                last_update[0] = now
                on_progress_sync(job)

        elif status == "finished":
            job.status = "merging"
            filename = d.get("filename")
            if filename:
                job.filename = os.path.basename(filename)
                job.target_filepath = filename
                final_file[0] = filename
            on_progress_sync(job)

    def postprocessor_hook(d: Dict[str, Any]):
        if check_cancelled():
            raise DownloadCancelledException("Download cancelled by user.")
        if d.get("status") == "started":
            job.status = "merging"
            on_progress_sync(job)
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
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "web"]
            }
        },
    }

    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    # Format selection logic
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
        import re
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

    # If file path extension changed during merging (e.g., .webm remuxed to .mp4 or .fXXX stripped)
    if final_file[0] and not os.path.exists(final_file[0]):
        import re
        base_cand = re.sub(r'\.f\d+$', '', os.path.splitext(final_file[0])[0])
        for ext_cand in [".mp4", ".mkv", ".webm", ".mp3", ".m4a"]:
            cand_path = base_cand + ext_cand
            if os.path.exists(cand_path):
                final_file[0] = cand_path
                break

    result_path = final_file[0] or ""
    if result_path and os.path.exists(result_path):
        job.filename = os.path.basename(result_path)
        job.target_filepath = result_path
        job.progress_percent = 100.0
        job.speed_str = "-- KB/s"
        job.eta_str = "Completed"
    return result_path

async def download_ytdlp(
    job: DownloadJob,
    on_progress: Callable[[DownloadJob], Any],
    check_cancelled: Callable[[], bool]
) -> str:
    """Run yt-dlp downloader asynchronously in a thread."""
    loop = asyncio.get_running_loop()

    def sync_progress_adapter(j: DownloadJob):
        # Schedule the async callback on the main loop
        asyncio.run_coroutine_threadsafe(on_progress(j), loop)

    return await asyncio.to_thread(_download_ytdlp_sync, job, sync_progress_adapter, check_cancelled)

