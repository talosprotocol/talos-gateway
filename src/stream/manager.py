import asyncio
import logging
import time
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from .types import ErrorMessage, ErrorCode, CloseCode, WSMsgType

logger = logging.getLogger(__name__)

class ConnectionManager:
    """
    Manages active WebSocket connections.
    Enforces backpressure: One Queue Per Connection.
    """
    def __init__(self):
        # session_id -> {ws, queue, filters}
        self.active_connections: Dict[str, Dict] = {}
        self.queue_limit = 1000  # Max pending messages before SLOW_CONSUMER
        self.background_tasks = set() # To hold references to consumer tasks

    def connect(self, websocket: WebSocket, session_id: str, filters: dict = None):
        # WebSocket is already accepted by session handshake
        self.active_connections[session_id] = {
            "type": "ws",
            "ws": websocket,
            "queue": asyncio.Queue(maxsize=self.queue_limit),
            "created_at": time.time(),
            "connected": True,
            "filters": filters or {}
        }
        logger.info(f"WS Connected: {session_id} with filters: {filters}")

        # Start the queue consumer for this connection
        task = asyncio.create_task(self._consumer_loop(session_id))
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)

    def connect_sse(self, session_id: str, filters: dict = None) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=self.queue_limit)
        self.active_connections[session_id] = {
            "type": "sse",
            "queue": queue,
            "created_at": time.time(),
            "connected": True,
            "filters": filters or {}
        }
        logger.info(f"SSE Connected: {session_id}")
        return queue

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            self.active_connections[session_id]["connected"] = False
            # We don't necessarily close the WS here if it's already closed
            # The consumer loop will exit
            del self.active_connections[session_id]
            logger.info(f"WS Disconnected: {session_id}")

    async def send_personal_message(self, message: dict, session_id: str):
        if session_id not in self.active_connections:
            return
        
        conn_data = self.active_connections[session_id]
        queue = conn_data["queue"]

        try:
            # Non-blocking put. If full, QueueFull is raised.
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(f"Session {session_id} is SLOW CONSUMER. Disconnecting.")
            await self._disconnect_slow_consumer(session_id)

    def _matches_filters(self, event: dict, filters: dict) -> bool:
        if not filters:
            return True
        
        for key, val in filters.items():
            if key in event and event[key] != val:
                return False
        return True

    async def broadcast_event(self, event: dict):
        """
        Broadcasts event to all authorized listeners.
        """
        # Snapshot keys to avoid modification during iteration
        for session_id in self.active_connections:
            conn = self.active_connections.get(session_id)
            if not conn:
                continue
                
            if not self._matches_filters(event, conn.get("filters")):
                continue

            # Wrap as WS Message
            msg = {
                "type": WSMsgType.EVENT,
                "event": event,
                "cursor": event.get("cursor"),
                "server_time": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            await self.send_personal_message(msg, session_id)

    async def _consumer_loop(self, session_id: str):
        """
        Dedicated coroutine for sending messages to a specific client.
        Enforces serial sending standard.
        """
        if session_id not in self.active_connections:
            return

        conn = self.active_connections[session_id]
        ws: WebSocket = conn["ws"]
        queue: asyncio.Queue = conn["queue"]

        try:
            while conn["connected"]:
                msg = await queue.get()
                
                # Check if it is a dictionary, use Pydantic dump if model?
                # Assuming dicts for serialization speed
                await ws.send_json(msg)
                queue.task_done()
        except WebSocketDisconnect:
            logger.info(f"Consumer loop: Client disconnected {session_id}")
            self.disconnect(session_id)
        except Exception as e:
            logger.error(f"Consumer loop error {session_id}: {e}")
            self.disconnect(session_id)

    async def _disconnect_slow_consumer(self, session_id: str):
        if session_id not in self.active_connections:
            return
            
        conn = self.active_connections[session_id]
        ws: WebSocket = conn["ws"]
        
        # Send Error Message
        err = ErrorMessage(
            code=ErrorCode.SLOW_CONSUMER,
            message="Message queue exceeded limit. You are too slow.",
            details={"limit": self.queue_limit}
        )
        try:
            await ws.send_json(err.model_dump())
            await ws.close(code=CloseCode.SLOW_CONSUMER)
        except Exception:
            pass # Socket might be dead already
        
        self.disconnect(session_id)

manager = ConnectionManager()
