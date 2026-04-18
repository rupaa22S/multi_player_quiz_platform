# websocket_manager.py - Manages all active WebSocket connections per room

import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections grouped by room_code.
    Supports broadcasting to all users in a room and
    sending targeted messages to individual connections.
    """

    def __init__(self):
        # room_code -> list of (websocket, user_id, user_name, is_admin)
        self.rooms: dict[str, list[dict]] = {}

    async def connect(self, websocket: WebSocket, room_code: str, user_id: int, user_name: str, is_admin: bool):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        if room_code not in self.rooms:
            self.rooms[room_code] = []

        self.rooms[room_code].append({
            "ws": websocket,
            "user_id": user_id,
            "user_name": user_name,
            "is_admin": is_admin,
        })
        logger.info(f"[WS] {user_name} (id={user_id}) connected to room {room_code}")

    def disconnect(self, websocket: WebSocket, room_code: str):
        """Remove a connection from the room registry."""
        if room_code in self.rooms:
            self.rooms[room_code] = [
                conn for conn in self.rooms[room_code]
                if conn["ws"] != websocket
            ]
            if not self.rooms[room_code]:
                del self.rooms[room_code]

    def get_connections(self, room_code: str) -> list[dict]:
        """Return all active connections for a room."""
        return self.rooms.get(room_code, [])

    def get_user_count(self, room_code: str) -> int:
        """Count non-admin users in a room."""
        return sum(
            1 for c in self.get_connections(room_code) if not c["is_admin"]
        )

    async def broadcast(self, room_code: str, message: dict, exclude_ws: WebSocket = None):
        """Send a message to all connections in a room, optionally excluding one."""
        dead = []
        for conn in self.get_connections(room_code):
            if conn["ws"] == exclude_ws:
                continue
            try:
                await conn["ws"].send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"[WS] Failed to send to {conn['user_name']}: {e}")
                dead.append(conn["ws"])

        # Clean up dead connections
        for ws in dead:
            self.disconnect(ws, room_code)

    async def send_to_user(self, room_code: str, user_id: int, message: dict):
        """Send a message to a specific user by user_id."""
        for conn in self.get_connections(room_code):
            if conn["user_id"] == user_id:
                try:
                    await conn["ws"].send_text(json.dumps(message))
                except Exception as e:
                    logger.warning(f"[WS] Failed to send to user {user_id}: {e}")
                break

    async def send_to_admin(self, room_code: str, message: dict):
        """Send a message only to the admin of a room."""
        for conn in self.get_connections(room_code):
            if conn["is_admin"]:
                try:
                    await conn["ws"].send_text(json.dumps(message))
                except Exception as e:
                    logger.warning(f"[WS] Failed to send to admin: {e}")
                break

    def get_user_list(self, room_code: str) -> list[dict]:
        """Return simplified user info for all non-admin connections."""
        return [
            {"user_id": c["user_id"], "user_name": c["user_name"]}
            for c in self.get_connections(room_code)
            if not c["is_admin"]
        ]


# Singleton instance shared across the application
manager = ConnectionManager()
