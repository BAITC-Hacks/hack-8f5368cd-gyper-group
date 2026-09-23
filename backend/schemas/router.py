from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


class Alternative(BaseModel):
    scenario_id: str
    confidence: float = Field(ge=0, le=1)
    label: str


class RouteDecision(BaseModel):
    scenario_id: str
    confidence: float = Field(ge=0, le=1)
    rationale: str
    language: Literal["ru", "kk", "mixed", "unknown"] = "unknown"
    extracted_parameters: dict[str, str] = Field(default_factory=dict)
    alternatives: list[Alternative] = Field(default_factory=list)
    handoff_recommended: bool = False


class ClientMessage(BaseModel):
    type: Literal["text", "audio", "reset"]
    text: str | None = None
    mime_type: str | None = None
