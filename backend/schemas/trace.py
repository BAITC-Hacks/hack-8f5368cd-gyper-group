from pydantic import BaseModel, Field

from schemas.router import RouteDecision


class StageLatency(BaseModel):
    stt_ms: float = 0
    router_ms: float = 0
    execution_ms: float = 0
    tts_ms: float = 0
    total_ms: float = 0


class TraceEvent(BaseModel):
    conversation_id: str
    decision: RouteDecision
    latency: StageLatency
    history_size: int
    router_mode: str
    timestamp: str


class ServerMessage(BaseModel):
    type: str = "turn_complete"
    transcript: str
    response_text: str
    audio_base64: str | None = None
    trace: TraceEvent
    operator_context: dict[str, object] | None = None
    warnings: list[str] = Field(default_factory=list)
