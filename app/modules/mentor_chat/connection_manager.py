import uuid

from fastapi import WebSocket

# In-memory, single-process — fine for this app's current deploy (one
# Uvicorn worker). Broadcasting a new message across multiple workers/
# instances would need a shared pub/sub (e.g. Redis) instead; not needed yet.
class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, list[WebSocket]] = {}

    async def connect(self, conversation_id: uuid.UUID, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(conversation_id, []).append(websocket)

    def disconnect(self, conversation_id: uuid.UUID, websocket: WebSocket) -> None:
        connections = self._connections.get(conversation_id)
        if not connections:
            return
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self._connections.pop(conversation_id, None)

    async def broadcast(self, conversation_id: uuid.UUID, payload: dict) -> None:
        for websocket in list(self._connections.get(conversation_id, [])):
            try:
                await websocket.send_json(payload)
            except Exception:
                # A dead socket here shouldn't break the send for everyone
                # else — disconnect() (via the route's own except/finally)
                # is what actually removes it from the list.
                pass


manager = ConnectionManager()
