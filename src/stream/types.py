from enum import Enum
from typing import Optional, Literal, Union, Dict, Any
from pydantic import BaseModel, Field
import time

class WSMsgType(str, Enum):
    INIT = "init"
    INIT_ACK = "init_ack"
    HEARTBEAT = "heartbeat"
    EVENT = "event"
    ERROR = "error"
    RECONNECT = "reconnect"

class ErrorCode(str, Enum):
    AUTH_FAILED = "AUTH_FAILED"
    CAPABILITY_EXPIRED = "CAPABILITY_EXPIRED"
    INVALID_MESSAGE = "INVALID_MESSAGE"
    RATE_LIMITED = "RATE_LIMITED"
    SLOW_CONSUMER = "SLOW_CONSUMER"
    INTERNAL_ERROR = "INTERNAL_ERROR"

class CloseCode(int, Enum):
    SLOW_CONSUMER = 4000
    AUTH_FAILED = 4001
    CAPABILITY_EXPIRED = 4002
    INVALID_FORMAT = 4003
    INTERNAL_ERROR = 4004
    POLICY_VIOLATION = 4005

class InitMessage(BaseModel):
    type: Literal[WSMsgType.INIT] = WSMsgType.INIT
    version: Literal[1] = 1 # Pydantic v2 way
    capability: str
    nonce: str
    ts: str  # ISO8601 string
    filters: Optional[Dict[str, Any]] = None

class InitAckMessage(BaseModel):
    type: Literal[WSMsgType.INIT_ACK] = WSMsgType.INIT_ACK
    session_id: str
    heartbeat_interval_ms: int

class HeartbeatMessage(BaseModel):
    type: Literal[WSMsgType.HEARTBEAT] = WSMsgType.HEARTBEAT
    last_cursor: str
    interval_ms: int

class EventMessage(BaseModel):
    type: Literal[WSMsgType.EVENT] = WSMsgType.EVENT
    event: Dict[str, Any]  # Full AuditEvent
    cursor: str
    server_time: str

class ErrorMessage(BaseModel):
    type: Literal[WSMsgType.ERROR] = WSMsgType.ERROR
    code: ErrorCode
    message: str
    details: Optional[Dict[str, Any]] = None

class ReconnectAdviceMessage(BaseModel):
    type: Literal[WSMsgType.RECONNECT] = WSMsgType.RECONNECT
    retry_after_ms: int

# Union type for receiving/parsing
WSMessage = Union[InitMessage, InitAckMessage, HeartbeatMessage, EventMessage, ErrorMessage, ReconnectAdviceMessage]
