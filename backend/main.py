from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.websocket import create_router
from config import get_settings
from services.executor import ScenarioExecutor
from services.llm_router import LLMRouter
from services.stt_service import STTService
from services.tts_service import TTSService

settings = get_settings()
app = FastAPI(title="Voice Router", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(create_router(LLMRouter(settings), ScenarioExecutor(), STTService(), TTSService(settings)))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "router": "llm" if settings.llm_api_key else "fallback"}