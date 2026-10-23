import os
import shutil
from typing import Dict, Any, Optional
from app.domain.exceptions import PathTraversalSecurityException
from app.utils import open_in_file_manager, sanitize_filename, format_bytes

class StorageService:
    """
    Storage & Delivery Microservice.
    Manages local filesystem isolation, path traversal guards, and disk space capacity.
    """
    def __init__(self, base_dir: str):
        self.base_dir = os.path.realpath(os.path.expanduser(base_dir))
        try:
            os.makedirs(self.base_dir, exist_ok=True)
        except OSError:
            # Serverless fallback for read-only environments (e.g. Vercel / AWS Lambda)
            self.base_dir = os.path.realpath("/tmp/Zdownloader")
            try:
                os.makedirs(self.base_dir, exist_ok=True)
            except Exception:
                pass

    def set_directory(self, new_dir: str) -> None:
        self.base_dir = os.path.realpath(os.path.expanduser(new_dir))
        try:
            os.makedirs(self.base_dir, exist_ok=True)
        except OSError:
            pass

    def is_safe_path(self, target_path: str) -> bool:
        """
        Validate that target_path strictly resides within base_dir.
        Protects against directory traversal (e.g. '../', absolute system paths).
        """
        if not target_path:
            return False
        try:
            resolved_base = os.path.realpath(self.base_dir)
            resolved_target = os.path.realpath(target_path)
            return os.path.commonpath([resolved_base, resolved_target]) == resolved_base
        except Exception:
            return False

    def has_sufficient_space(self, required_bytes: Optional[int] = None, buffer_mb: int = 50) -> bool:
        """
        Verify that target storage volume has adequate free space.
        Leaves at least buffer_mb headroom.
        """
        try:
            _, _, free = shutil.disk_usage(self.base_dir)
            needed = (required_bytes or 0) + (buffer_mb * 1024 * 1024)
            return free >= needed
        except Exception:
            return True

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
        if not self.is_safe_path(target_path):
            raise PathTraversalSecurityException(f"Access denied: {target_path} is outside the authorized download directory.")
        if not os.path.exists(target_path):
            return False
        return open_in_file_manager(target_path)

storage_service = StorageService(os.path.expanduser("~/Downloads/Zdownloader"))

