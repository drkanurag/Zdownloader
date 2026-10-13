import os
import shutil
from typing import Dict, Any, Optional
from app.utils import open_in_file_manager, sanitize_filename, format_bytes

class StorageService:
    """
    Storage & Delivery Microservice.
    Manages local filesystem isolation, path validation, and disk space capacity.
    """
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def set_directory(self, new_dir: str) -> None:
        self.base_dir = new_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def get_disk_usage(self) -> Dict[str, Any]:
        """Inspect storage volume capacity (total, used, free)."""
        try:
            total, used, free = shutil.disk_usage(self.base_dir)
            return {
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "total_str": format_bytes(total),
                "free_str": format_bytes(free),
                "percent_free": round((free / total) * 100, 1)
            }
        except Exception:
            return {"error": "Unable to query disk capacity"}

    def open_folder(self) -> bool:
        return open_in_file_manager(self.base_dir)

    def open_file(self, target_path: str) -> bool:
        if not os.path.exists(target_path):
            return False
        return open_in_file_manager(target_path)

storage_service = StorageService(os.path.expanduser("~/Downloads/Zdownloader"))

