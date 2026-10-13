import json
import asyncio
from typing import Set, Dict, Any
from fastapi import WebSocket
from app.core.event_bus import event_bus
from app.domain.events import JobProgressEvent, JobCompletedEvent, JobFailedEvent, JobCancelledEvent

class WebSocketBroadcaster:
    """Manages active WebSockets and bridges EventBus events to connected browser tabs."""
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._setup_event_listeners()

    def _setup_event_listeners(self):
        # Register EventBus subscribers for live push updates
        async def on_progress(event: JobProgressEvent):
            await self.broadcast({
                "type": "job_update",
                "job": {
                    "id": event.job_id,
                    "status": event.status,
                    "progress_percent": event.progress_percent,
                    "downloaded_bytes": event.downloaded_bytes,
                    "total_bytes": event.total_bytes,
                    "speed_str": event.speed_str,
                    "eta_str": event.eta_str,
                }
            })

        async def on_completed(event: JobCompletedEvent):
            await self.broadcast({
                "type": "job_update",
                "job": {
                    "id": event.job_id,
                    "status": "completed",
                    "progress_percent": 100.0,
                    "target_filepath": event.filepath,
                    "filename": event.filename,
                    "downloaded_bytes": event.total_bytes,
                    "speed_str": "-- KB/s",
                    "eta_str": "Completed"
                }
            })

        async def on_failed(event: JobFailedEvent):
            await self.broadcast({
                "type": "job_update",
                "job": {
                    "id": event.job_id,
                    "status": "error",
                    "error_message": event.error_message
                }
            })

        async def on_cancelled(event: JobCancelledEvent):
            await self.broadcast({
                "type": "job_update",
                "job": {
                    "id": event.job_id,
                    "status": "cancelled",
                    "error_message": "Cancelled by user"
                }
            })

        # Subscribe handlers to EventBus
        event_bus.subscribe(JobProgressEvent, on_progress)
        event_bus.subscribe(JobCompletedEvent, on_completed)
        event_bus.subscribe(JobFailedEvent, on_failed)
        event_bus.subscribe(JobCancelledEvent, on_cancelled)

        # Wire native clipboard monitor to WebSocket broadcast
        from app.services.clipboard_service import clipboard_service
        def on_clipboard_link(url: str, urls: list):
            try:
                import app.main as main_mod
                loop = main_mod.main_loop
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.broadcast({
                            "type": "clipboard_detected",
                            "url": url,
                            "urls": urls
                        }),
                        loop
                    )
            except Exception as e:
                print(f"[Clipboard Broadcast Error]: {e}")

        clipboard_service.on_link_detected_callbacks.append(on_clipboard_link)

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)

    async def broadcast(self, payload: Dict[str, Any]):
        if not self.active_connections:
            return
        dead = set()
        msg = json.dumps(payload)
        for conn in list(self.active_connections):
            try:
                await conn.send_text(msg)
            except Exception:
                dead.add(conn)
        for d in dead:
            self.active_connections.discard(d)

ws_broadcaster = WebSocketBroadcaster()
