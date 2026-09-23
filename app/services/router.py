import json
import re
from time import perf_counter
from typing import Any

try:
    from openai import AsyncOpenAI
except ImportError:  # Supports an offline hackathon demo without external packages.
    AsyncOpenAI = None  # type: ignore[assignment,misc]

from app.config import Settings
from app.core.vector_index import VectorIndex

_OPERATOR_RE = re.compile(r"\b(оператор|соедините с оператором|живой человек|операторға бағыттау)\b", re.IGNORECASE)
_SLOT_PATTERNS = {
    "card_last4": re.compile(r"\b(?:карта|card)?\s*(\d{4})\b", re.IGNORECASE),
    "amount": re.compile(r"\b(\d+(?:[.,]\d{1,2})?)\s*(?:тг|тенге|kzt|руб|rub)\b", re.IGNORECASE),
    "phone": re.compile(r"\+?\d[\d ()-]{8,}\d"),
}
_SLOT_ALIASES = {
    "region": {"алмат": "almaty", "астан": "astana"},
    "vehicle_type": {
        "легков": "car",
        "жеңіл": "car",
        "грузов": "truck",
        "жүк": "truck",
        "мото": "motorcycle",
    },
}


class HybridRouter:
    """Two-stage router: local vector retrieval followed by an optional LLM adjudicator."""

    def __init__(self, settings: Settings, index: VectorIndex, slot_catalog: dict[str, Any] | None = None) -> None:
        self.settings = settings
        self.index = index
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key and AsyncOpenAI else None
        self.slot_catalog = slot_catalog or {}

    async def route(self, user_text: str, history: list[dict[str, str]]) -> dict[str, Any]:
        started = perf_counter()
        user_turns = [turn.get("content", "") for turn in history if turn.get("role") == "user"]
        context = " ".join(user_turns[-2:])
        search_text = f"{context} {user_text}".strip() if context else user_text.strip()

        retrieval_started = perf_counter()
        candidates = self.index.search(user_text)
        if not candidates or candidates[0]["score"] < 0.45:
            candidates = self.index.search(search_text)
        retrieval_ms = round((perf_counter() - retrieval_started) * 1000, 2)

        if _OPERATOR_RE.search(user_text):
            decision = self._handover(candidates, "Клиент запросил соединение с оператором.")
            llm_ms = 0.0
        elif self.client and self._needs_llm(candidates):
            llm_started = perf_counter()
            try:
                decision = await self._llm_decision(user_text, history, candidates)
            except Exception as error:  # External service must not break a call.
                decision = self._local_decision(candidates, f"LLM unavailable: {type(error).__name__}")
            llm_ms = round((perf_counter() - llm_started) * 1000, 2)
        elif self.client:
            decision = self._local_decision(candidates, "Локальное решение: высокая уверенность по кандидатам.")
            llm_ms = 0.0
        else:
            decision = self._local_decision(candidates, "Локальное решение: API-ключ не настроен.")
            llm_ms = 0.0

        local_slots = self._extract_slots(user_text)
        llm_slots = {
            name: value
            for name, value in decision.get("extracted_slots", {}).items()
            if value not in (None, "", [], {})
        }
        decision["extracted_slots"] = {**llm_slots, **local_slots}
        selected = next(
            (item["scenario"] for item in candidates if item["scenario"]["id"] == decision["selected_scenario_id"]),
            None,
        )
        if selected:
            decision["required_slots"] = selected.get("slots", {}).get("required", [])
            decision["actions"] = selected.get("actions", [])
            decision["requires_confirmation"] = selected.get("requires_confirmation", False)
        decision["language"] = self._detect_language(user_text)
        if decision["confidence"] < self.settings.router_confidence_threshold:
            decision = self._handover(candidates, "Недостаточная уверенность маршрутизации.", decision)
        decision["candidates"] = [
            {"id": item["scenario"]["id"], "title_ru": item["scenario"]["title_ru"], "score": item["score"]}
            for item in candidates
        ]
        decision["latency"] = {
            "candidate_retrieval_ms": retrieval_ms,
            "llm_routing_ms": llm_ms,
            "routing_total_ms": round((perf_counter() - started) * 1000, 2),
        }
        return decision

    @staticmethod
    def _needs_llm(candidates: list[dict[str, Any]]) -> bool:
        if len(candidates) < 2:
            return True
        return candidates[0]["score"] - candidates[1]["score"] < 0.35

    def _local_decision(self, candidates: list[dict[str, Any]], note: str) -> dict[str, Any]:
        selected = candidates[0]["scenario"]
        score = candidates[0]["score"]
        confidence = min(0.92, max(0.66, round(0.66 + score * 0.26, 2)))
        alternatives = [item["scenario"]["id"] for item in candidates[1:]]
        return {
            "selected_scenario_id": selected["id"],
            "confidence": confidence,
            "reasoning_ru": f"{note} Выбран сценарий: {selected['title_ru']}.",
            "reasoning_kz": f"{note} Таңдалған сценарий: {selected['title_kz']}.",
            "alternative_scenarios": alternatives,
            "extracted_slots": {},
            "requires_operator": False,
        }

    def _handover(
        self, candidates: list[dict[str, Any]], reason: str, previous: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        previous = previous or {}
        return {
            "selected_scenario_id": "OPERATOR_HANDOVER",
            "confidence": previous.get("confidence", 0.6),
            "reasoning_ru": reason,
            "reasoning_kz": "Операторға бағыттау қажет.",
            "alternative_scenarios": [item["scenario"]["id"] for item in candidates],
            "extracted_slots": previous.get("extracted_slots", {}),
            "requires_operator": True,
        }

    async def _llm_decision(
        self, user_text: str, history: list[dict[str, str]], candidates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        candidate_data = [item["scenario"] for item in candidates]
        prompt = f"""You route Halyk Bank voice calls in Russian, Kazakh, and mixed RU/KZ speech.
A new action item in the latest message overrides the previous topic. Select only a candidate ID,
or OPERATOR_HANDOVER if confidence is below 0.65 or a human is requested. Extract relevant slots.
Return strict JSON with selected_scenario_id, confidence (0..1), reasoning_ru, reasoning_kz,
alternative_scenarios, extracted_slots, requires_operator.
Candidates: {json.dumps(candidate_data, ensure_ascii=False)}
History: {json.dumps(history[-3:], ensure_ascii=False)}
Latest user message: {user_text}"""
        response = await self.client.chat.completions.create(
            model=self.settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a precise bank call routing engine. Never invent IDs."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        decision = json.loads(content)
        allowed = {item["scenario"]["id"] for item in candidates} | {"OPERATOR_HANDOVER"}
        if decision.get("selected_scenario_id") not in allowed:
            raise ValueError("LLM returned a scenario outside supplied candidates")
        decision["confidence"] = float(decision.get("confidence", 0))
        decision["requires_operator"] = bool(decision.get("requires_operator", False))
        return decision

    def _extract_slots(self, text: str) -> dict[str, str]:
        slots = {}
        for name, pattern in _SLOT_PATTERNS.items():
            match = pattern.search(text)
            if match:
                slots[name] = match.group(1) if match.groups() else match.group(0)
        for slot in self.slot_catalog.get("slots", []):
            pattern = slot.get("pattern")
            if not pattern:
                continue
            match = re.search(pattern.strip("^$"), text, re.IGNORECASE)
            if match:
                slots[slot["name"]] = match.group(0)
        lowered = text.lower()
        for slot_name, aliases in _SLOT_ALIASES.items():
            for phrase, value in aliases.items():
                if phrase in lowered:
                    slots[slot_name] = value
                    break
        return slots

    @staticmethod
    def _detect_language(text: str) -> str:
        kazakh_letters = sum(character in "әіңғүұқөһ" for character in text.lower())
        cyrillic_letters = sum(character.isalpha() and "а" <= character.lower() <= "я" for character in text)
        if kazakh_letters and cyrillic_letters > kazakh_letters * 3:
            return "mixed"
        return "kk" if kazakh_letters else "ru"
