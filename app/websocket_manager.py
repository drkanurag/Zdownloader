import json
from typing import Set, Dict, Any
from fastapi import WebSocket

class WebSocketManager:
    """Manages active WebSocket connections to push live job progress updates."""
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients; remove dead connections."""
        if not self.active_connections:
            return
        dead_connections = set()
        data_text = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(data_text)
            except Exception:
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)

ws_manager = WebSocketManager()

