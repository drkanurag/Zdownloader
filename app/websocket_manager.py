"""
DEPRECATED: app.websocket_manager has been refactored to app.api.websocket.
This module provides backward-compatible re-exports delegating to ws_broadcaster.
"""
import warnings
from typing import Set, Dict, Any
from fastapi import WebSocket
from app.api.websocket import WebSocketBroadcaster, ws_broadcaster

warnings.warn(
    "app.websocket_manager is deprecated; use app.api.websocket instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export WebSocketBroadcaster as WebSocketManager and ws_broadcaster as ws_manager
WebSocketManager = WebSocketBroadcaster
ws_manager = ws_broadcaster

__all__ = [
    "WebSocketManager",
    "ws_manager",
]
