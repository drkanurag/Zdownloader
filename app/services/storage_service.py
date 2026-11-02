import os
import shutil
from typing import Dict, Any, Optional
from app.config import DEFAULT_DOWNLOAD_DIR
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

    def has_sufficient_space(self, required_bytes: Optional[int] = None, buffer_mb: int = 50, target_dir: Optional[str] = None) -> bool:
        """
        Verify that target storage volume has adequate free space.
        Leaves at least buffer_mb headroom.
        """
        check_dir = target_dir or self.base_dir
        try:
            # If target_dir doesn't exist yet, inspect its parent directory
            inspect_dir = check_dir
            while inspect_dir and not os.path.exists(inspect_dir):
                parent = os.path.dirname(inspect_dir)
                if parent == inspect_dir:
                    break
                inspect_dir = parent
            
            _, _, free = shutil.disk_usage(inspect_dir or self.base_dir)
            needed = (required_bytes or 0) + (buffer_mb * 1024 * 1024)
            return free >= needed
        except Exception:
            return True

    def get_disk_usage(self, target_dir: Optional[str] = None) -> Dict[str, Any]:
        """Inspect storage volume capacity (total, used, free)."""
        check_dir = target_dir or self.base_dir
        try:
            inspect_dir = check_dir
            while inspect_dir and not os.path.exists(inspect_dir):
                parent = os.path.dirname(inspect_dir)
                if parent == inspect_dir:
                    break
                inspect_dir = parent
                
            total, used, free = shutil.disk_usage(inspect_dir or self.base_dir)
            return {
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": free,
                "total_str": format_bytes(total),
                "free_str": format_bytes(free),
                "percent_free": round((free / total) * 100, 1) if total > 0 else 0
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

storage_service = StorageService(DEFAULT_DOWNLOAD_DIR)
