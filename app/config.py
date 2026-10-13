import os
from pathlib import Path
from pydantic import BaseModel

DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "Zdownloader")
HISTORY_FILE = str(Path.home() / ".zdownloader_history.json")
QUEUE_FILE = str(Path.home() / ".zdownloader_queue.json")
CONFIG_FILE = str(Path.home() / ".zdownloader_config.json")

class AppSettings(BaseModel):
    download_dir: str = DEFAULT_DOWNLOAD_DIR
    max_concurrent_downloads: int = 10
    auto_clear_completed: bool = True
    default_quality: str = "highest"  # highest, 1080p, 720p, audio_only
    host: str = "127.0.0.1"
    port: int = 8765

# Ensure default download directory exists
os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)

