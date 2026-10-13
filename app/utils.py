import os
import re
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional

def get_ffmpeg_path() -> Optional[str]:
    """Locate FFmpeg executable: from local bin, imageio-ffmpeg, or system PATH."""
    # 1. Try local bin folder
    local_bin = Path(__file__).resolve().parent.parent / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    if local_bin.exists():
        bin_dir = str(local_bin.parent)
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        return str(local_bin)

    # 2. Try imageio_ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_bin and os.path.exists(ffmpeg_bin):
            bin_dir = os.path.dirname(ffmpeg_bin)
            if bin_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            return ffmpeg_bin
    except Exception:
        pass

    # 3. Try system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    return None

def format_bytes(size_bytes: Optional[int | float]) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if size_bytes is None or size_bytes < 0:
        return "Unknown size"
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_idx = 0
    size = float(size_bytes)
    while size >= 1024.0 and unit_idx < len(units) - 1:
        size /= 1024.0
        unit_idx += 1
    return f"{size:.1f} {units[unit_idx]}" if unit_idx > 0 else f"{int(size)} B"

def format_speed(bytes_per_sec: Optional[int | float]) -> str:
    """Format bytes per second into human-readable download speed."""
    if bytes_per_sec is None or bytes_per_sec <= 0:
        return "-- KB/s"
    return f"{format_bytes(bytes_per_sec)}/s"

def format_seconds(seconds: Optional[int | float]) -> str:
    """Format duration in seconds into HH:MM:SS or MM:SS."""
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def sanitize_filename(name: str) -> str:
    """Sanitize filename to prevent filesystem errors or directory traversal."""
    # Remove directory separators and illegal characters on Windows (<>:"/\|?*)
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", name)
    sanitized = sanitized.strip().strip(". ")
    if not sanitized:
        sanitized = "downloaded_file"
    return sanitized[:200]

def open_in_file_manager(target_path: str) -> bool:
    """Open the file or enclosing directory in the default file manager (Explorer on Windows)."""
    try:
        path = Path(target_path).resolve()
        if not path.exists():
            # If target file doesn't exist yet, open the parent directory
            path = path.parent
            if not path.exists():
                return False

        if sys.platform == "win32":
            resolved = str(path.resolve())
            try:
                if path.is_file():
                    subprocess.Popen(f'explorer.exe /select,"{resolved}"')
                else:
                    subprocess.Popen(f'explorer.exe "{resolved}"')
                return True
            except Exception:
                # Fallback to shell startfile
                try:
                    os.startfile(resolved if path.is_dir() else str(path.parent.resolve()))
                    return True
                except Exception as ex:
                    print(f"Error opening in Explorer: {ex}")
                    return False
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if path.is_file() else "", str(path)])
            return True
        else:
            subprocess.Popen(["xdg-open", str(path.parent if path.is_file() else path)])
            return True
    except Exception as e:
        print(f"Error opening file manager for {target_path}: {e}")
        return False

