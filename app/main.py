from contextlib import asynccontextmanager
import logging
from time import perf_counter
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.core.scenario_loader import ScenarioLoader
from app.core.vector_index import VectorIndex
from app.services.action_executor import ActionExecutor
from app.services.router import HybridRouter
from app.services.stt_tts import SpeechService, decode_audio_payload

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    loader = ScenarioLoader(settings.data_dir)
    scenarios = loader.load_scenarios()
    app.state.assets = loader.load_assets()
    app.state.router = HybridRouter(settings, VectorIndex(scenarios), app.state.assets["slots"])
    app.state.executor = ActionExecutor(app.state.assets)
    app.state.speech = SpeechService(settings)
    yield


app = FastAPI(title="Halyk Voice Router", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "scenarios": len(app.state.router.index.scenarios)}


@app.websocket("/ws/router")
async def router_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    history: list[dict[str, str]] = []
    collected_slots: dict[str, Any] = {}
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") not in {"route", "route_audio"}:
                await websocket.send_json({"type": "error", "message": "Unsupported event type"})
                continue
            started = perf_counter()
            audio = decode_audio_payload(message.get("audio_base64"))
            if message.get("type") == "route_audio":
                logger.info("Received voice payload: bytes=%s mime=%s", len(audio or b""), message.get("audio_mime"))
            try:
                transcript, stt_ms = await app.state.speech.transcribe(
                    message.get("transcript"),
                    audio,
                    message.get("audio_mime", "audio/webm"),
                    message.get("language_hint"),
                )
            except RuntimeError as error:
                await websocket.send_json({"type": "error", "message": str(error)})
                continue
            except Exception:
                logger.exception("Voice transcription failed")
                await websocket.send_json({"type": "error", "message": "Не удалось распознать аудио. Попробуйте ещё раз."})
                continue
            if not transcript:
                await websocket.send_json({"type": "error", "message": "Речь не распознана. Попробуйте ещё раз."})
                continue
            await websocket.send_json({"type": "trace", "step": "transcript", "transcript": transcript, "stt_ms": stt_ms})
            decision = await app.state.router.route(transcript, history)
            collected_slots.update(decision["extracted_slots"])
            decision["extracted_slots"] = dict(collected_slots)
            missing_slots = [
                name for name in decision.get("required_slots", [])
                if collected_slots.get(name) in (None, "", [], {})
            ]
            execution = []
            if not missing_slots and not decision["requires_operator"]:
                execution = app.state.executor.execute_many(decision.get("actions", []), collected_slots)
            decision["missing_slots"] = missing_slots
            decision["action_results"] = execution
            await websocket.send_json({"type": "trace", "step": "routing", **decision})
            response_text = response_for(decision, app.state.assets, execution)
            speech = await app.state.speech.synthesize(response_text, decision.get("language", "ru"))
            total_ms = round((perf_counter() - started) * 1000, 2)
            event = {
                "type": "response",
                "transcript": transcript,
                "reply": speech["text"],
                "audio_base64": speech["audio_base64"],
                "audio_mime": speech["audio_mime"],
                "decision": decision,
                "latency": {**decision["latency"], "stt_ms": stt_ms, "tts_ms": speech["tts_ms"], "total_ms": total_ms},
            }
            await websocket.send_json(event)
            history.extend([{"role": "user", "content": transcript}, {"role": "assistant", "content": speech["text"]}])
            history = history[-6:]
    except WebSocketDisconnect:
        return


def response_for(decision: dict[str, Any], assets: dict[str, Any], execution: list[dict[str, Any]]) -> str:
    catalog = assets.get("scenario_catalog", {}).get("scenarios", [])
    scenario = next((item for item in catalog if item["scenario_id"] == decision["selected_scenario_id"]), None)
    language = "kk" if decision.get("language") == "kk" else "ru"
    if decision.get("missing_slots"):
        slot_name = decision["missing_slots"][0]
        slot = next((item for item in assets["slots"].get("slots", []) if item["name"] == slot_name), {})
        return slot.get("prompt", {}).get(language) or f"Укажите, пожалуйста, {slot_name}."
    if scenario:
        closing = scenario.get("responses", {}).get(language, {}).get("closing")
        if closing and not decision.get("missing_slots"):
            fmt_data = dict(decision.get("extracted_slots", {}))
            for item in execution:
                if item.get("status") == "ok" and isinstance(item.get("result"), dict):
                    fmt_data.update(item["result"])
            try:
                return closing.format(**fmt_data)
            except Exception:
                pass
        if any(item["status"] == "awaiting_confirmation" for item in execution):
            return "Подтвердите действие, ответив «да»." if language == "ru" else "Әрекетті растаңыз: «иә» деп жауап беріңіз."
        return scenario.get("responses", {}).get(language, {}).get("opening") or scenario["description"]
    if decision.get("selected_scenario_id") == "OPERATOR_HANDOVER":
        return (
            "Соединяю с оператором. Пожалуйста, подождите..." if language == "ru"
            else "Оператормен байланыстырамын. Күте тұрыңыз..."
        )
    return (
        f"Запрос маршрутизирован: {decision['selected_scenario_id']}. "
        "Уточните детали, чтобы продолжить."
    )


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_: Request, error: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(error)})
