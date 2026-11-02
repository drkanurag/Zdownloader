import os
import sys
import json
import secrets
import logging
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel

logger = logging.getLogger("zdownloader.config")

is_serverless = os.environ.get("VERCEL") == "1" or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") is not None

def get_app_data_dir() -> Path:
    """Resolve a guaranteed writable directory for app state, queue, and credentials."""
    candidates = []
    
    # 1. Explicit environment variable override
    env_dir = os.environ.get("ZDOWNLOADER_DATA_DIR")
    if env_dir:
        candidates.append(Path(env_dir))

    # 2. Serverless environment: strictly /tmp
    if is_serverless:
        candidates.append(Path("/tmp/zdownloader_data"))

    # 3. Windows standard local application data
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Zdownloader")

    # 4. User home directory hidden folder
    try:
        candidates.append(Path.home() / ".zdownloader")
    except Exception:
        pass

    # 5. OS temporary directory fallback
    temp_dir = os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp"
    candidates.append(Path(temp_dir) / "zdownloader_data")

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # Verify write permissions with a temporary touch
            test_file = candidate / f".write_test_{secrets.token_hex(4)}"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            return candidate.resolve()
        except Exception:
            continue

    # Absolute fallback to current directory
    cwd = Path(".").resolve() / ".zdownloader_data"
    cwd.mkdir(parents=True, exist_ok=True)
    return cwd

DATA_DIR = get_app_data_dir()
HISTORY_FILE = str(DATA_DIR / "history.json")
QUEUE_FILE = str(DATA_DIR / "queue.json")
CONFIG_FILE = str(DATA_DIR / "config.json")
TOKEN_FILE = str(DATA_DIR / "pairing_token.txt")

def get_default_download_dir() -> str:
    """Resolve default media download destination."""
    if is_serverless:
        return "/tmp/Zdownloader"

    env_dl = os.environ.get("ZDOWNLOADER_DOWNLOAD_DIR")
    if env_dl:
        return os.path.realpath(os.path.expanduser(env_dl))

    try:
        home_dl = Path.home() / "Downloads" / "Zdownloader"
        home_dl.mkdir(parents=True, exist_ok=True)
        return str(home_dl.resolve())
    except Exception:
        fallback = DATA_DIR / "downloads"
        fallback.mkdir(parents=True, exist_ok=True)
        return str(fallback.resolve())

DEFAULT_DOWNLOAD_DIR = get_default_download_dir()

def get_or_create_pairing_token() -> str:
    """Retrieve or generate local security pairing token for API & WebSocket authentication."""
    env_token = os.environ.get("ZDOWNLOADER_TOKEN")
    if env_token and env_token.strip():
        return env_token.strip()

    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                token = f.read().strip()
                if token:
                    return token
    except Exception:
        pass

    # Generate a fresh 256-bit cryptographically secure token
    new_token = secrets.token_hex(16)
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(new_token)
    except Exception as e:
        logger.warning(f"Could not persist pairing token to {TOKEN_FILE}: {e}")

    return new_token

PAIRING_TOKEN = get_or_create_pairing_token()

def atomic_write_json(filepath: str, data: Any) -> bool:
    """Safely and atomically write JSON data to avoid partial file corruption."""
    try:
        target_path = Path(filepath)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f".tmp_{target_path.name}_{secrets.token_hex(4)}"
        
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, target_path)
        return True
    except Exception as e:
        logger.error(f"Failed to persist state atomically to {filepath}: {e}")
        return False

class AppSettings(BaseModel):
    download_dir: str = DEFAULT_DOWNLOAD_DIR
    max_concurrent_downloads: int = 10
    auto_clear_completed: bool = True
    default_quality: str = "highest"  # highest, 1080p, 720p, audio_only
    host: str = "127.0.0.1"
    port: int = 8765
    auth_enabled: bool = True
