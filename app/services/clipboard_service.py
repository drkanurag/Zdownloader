import sys
import re
import time
import ctypes
import threading
import asyncio
from typing import Optional, List, Callable, Dict, Any

URL_REGEX = re.compile(r'https?://(?:(?!https?://)[^\s<>"\'`])+')

class ClipboardMonitorService:
    """
    High-Performance Native Windows Clipboard Monitor.
    
    Uses Windows GetClipboardSequenceNumber() for sub-microsecond O(1) change detection.
    When a user copies a media link (anywhere in Windows: browser, chat, etc.),
    it automatically detects the URL and broadcasts it in real-time to the web UI.
    """
    def __init__(self):
        self.enabled: bool = True
        self.last_seq: int = 0
        self.last_url: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self.on_link_detected_callbacks: List[Callable[[str, List[str]], Any]] = []

    def get_clipboard_text(self) -> Optional[str]:
        """Read unicode text from Windows clipboard via pure ctypes."""
        if sys.platform != "win32":
            return None

        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            user32.OpenClipboard.argtypes = [ctypes.c_void_p]
            user32.OpenClipboard.restype = ctypes.c_bool
            user32.GetClipboardData.argtypes = [ctypes.c_uint]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            user32.CloseClipboard.restype = ctypes.c_bool

            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalUnlock.restype = ctypes.c_bool

            if not user32.OpenClipboard(None):
                return None
            try:
                handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
                if not handle:
                    return None
                ptr = kernel32.GlobalLock(handle)
                if not ptr:
                    return None
                try:
                    return ctypes.c_wchar_p(ptr).value
                finally:
                    kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
        except Exception:
            return None

    def extract_urls(self, text: Optional[str]) -> List[str]:
        """Extract valid HTTP/HTTPS URLs from text, cleanly separating concatenated URLs."""
        if not text:
            return []
        matches = URL_REGEX.findall(text)
        cleaned = []
        for m in matches:
            u = m.strip().rstrip(".,;)>]")
            if u and (u.startswith("http://") or u.startswith("https://")):
                cleaned.append(u)
        return list(dict.fromkeys(cleaned))

    def start(self):
        """Start the background clipboard watcher thread."""
        if self._running or sys.platform != "win32":
            return
        self._running = True

        # Initialize sequence number
        try:
            self.last_seq = ctypes.windll.user32.GetClipboardSequenceNumber()
        except Exception:
            self.last_seq = 0

        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop clipboard watcher thread."""
        self._running = False

    def _monitor_loop(self):
        user32 = ctypes.windll.user32
        while self._running:
            try:
                if self.enabled:
                    current_seq = user32.GetClipboardSequenceNumber()
                    if current_seq != self.last_seq:
                        self.last_seq = current_seq
                        text = self.get_clipboard_text()
                        urls = self.extract_urls(text)
                        if urls:
                            first_url = urls[0]
                            self.last_url = first_url
                            for cb in self.on_link_detected_callbacks:
                                try:
                                    cb(first_url, urls)
                                except Exception as e:
                                    print(f"[Clipboard Callback Error]: {e}")
            except Exception as e:
                pass

            time.sleep(0.3)

clipboard_service = ClipboardMonitorService()

