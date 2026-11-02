import os
import sys
import time
import webbrowser
import threading
import uvicorn
from app.config import PAIRING_TOKEN

def open_browser(url: str, delay_seconds: float = 1.2):
    """Wait briefly for server to boot, then open the browser tab with pairing token."""
    time.sleep(delay_seconds)
    print(f"\n[Zdownloader] Opening browser at {url}...")
    webbrowser.open(url)

def main():
    host = "127.0.0.1"
    port = 8765
    url = f"http://{host}:{port}/?token={PAIRING_TOKEN}"

    print("=" * 64)
    print("            ZDOWNLOADER - LOCAL AGENT & WEB ENGINE              ")
    print("=" * 64)
    print(f" * Local Agent API:  http://{host}:{port}")
    print(f" * Pairing Token:    {PAIRING_TOKEN}")
    print(f" * WebSocket Stream: ws://{host}:{port}/ws?token={PAIRING_TOKEN}")
    print(" * Press Ctrl+C in this terminal to shut down.")
    print("=" * 64)

    # Launch browser in a background daemon thread
    browser_thread = threading.Thread(target=open_browser, args=(url,), daemon=True)
    browser_thread.start()

    # Start Uvicorn ASGI server
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=False
    )

if __name__ == "__main__":
    main()
