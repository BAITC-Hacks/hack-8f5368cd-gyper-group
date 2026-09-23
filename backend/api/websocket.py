import asyncio
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from schemas.router import ClientMessage
from schemas.trace import ServerMessage, StageLatency, TraceEvent
from services.context_manager import ConversationContext
from services.executor import ScenarioExecutor
from services.llm_router import LLMRouter
from services.stt_service import STTService
from services.tts_service import TTSService


def create_router(router: LLMRouter, executor: ScenarioExecutor, stt: STTService, tts: TTSService) -> APIRouter:
    api = APIRouter()

    @api.websocket("/ws/voice")
    async def voice_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        conversation_id = str(uuid4())
        context = ConversationContext()
        try:
            while True:
                payload = ClientMessage.model_validate_json(await websocket.receive_text())
                if payload.type == "reset":
                    context.reset()
                    await websocket.send_json({"type": "reset_complete"})
                    continue
                started = time.perf_counter()
                transcript = payload.text or ""
                stt_ms = 0.0
                warnings: list[str] = []
                if payload.type == "audio":
                    transcript, stt_ms = await stt.transcribe(b"", payload.mime_type)
                    if not transcript:
                        warnings.append("STT provider is not configured. Use the text channel for this demo.")
                        transcript = "Не удалось распознать аудио"
                context.add_turn("user", transcript)
                decision, router_ms, mode = await router.route(transcript, list(context.history), payload.language)
                context.record_route(decision.scenario_id, decision.extracted_parameters)
                response_text, execution_ms = await executor.execute(decision)
                context.add_turn("assistant", response_text)
                audio_base64, tts_ms = await tts.synthesize(response_text, decision.language)
                latency = StageLatency(stt_ms=round(stt_ms, 1), router_ms=round(router_ms, 1), execution_ms=round(execution_ms, 1), tts_ms=round(tts_ms, 1), total_ms=round((time.perf_counter() - started) * 1000, 1))
                trace = TraceEvent(conversation_id=conversation_id, decision=decision, latency=latency, history_size=len(context.history), router_mode=mode, timestamp=datetime.now(timezone.utc).isoformat())
                server_message = ServerMessage(transcript=transcript, response_text=response_text, audio_base64=audio_base64, trace=trace, operator_context=context.snapshot_for_operator() if decision.handoff_recommended else None, warnings=warnings)
                await websocket.send_json(server_message.model_dump())
        except WebSocketDisconnect:
            return

    return api
