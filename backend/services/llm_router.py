import json
import re
import time
from pathlib import Path

from openai import AsyncOpenAI

from config import Settings
from schemas.router import Alternative, RouteDecision, Turn


class LLMRouter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        data_path = Path(__file__).resolve().parents[1] / "data" / "scenarios.json"
        self.scenarios: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))
        self.by_id = {item["scenario_id"]: item for item in self.scenarios}
        self.client = (
            AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
            if settings.llm_api_key
            else None
        )

    async def route(self, text: str, history: list[Turn], language: str | None = None) -> tuple[RouteDecision, float, str]:
        started = time.perf_counter()
        if self.client:
            try:
                decision = await self._route_with_llm(text, history, language)
                return decision, (time.perf_counter() - started) * 1000, "llm"
            except Exception:
                # Preserve the voice flow under provider rate limits and network failures.
                pass
        decision = self._fallback_route(text, history, language)
        return decision, (time.perf_counter() - started) * 1000, "fallback"

    async def _route_with_llm(self, text: str, history: list[Turn], language: str | None = None) -> RouteDecision:
        catalog = [{key: item[key] for key in ("scenario_id", "label", "keywords")} for item in self.scenarios]
        prompt = (
            "You route multilingual Halyk Bank voice calls. Select exactly one scenario from this catalog. "
            "Support Russian, Kazakh, and code-switching. Return JSON only with scenario_id, confidence, "
            "rationale (brief, in caller language), language (ru|kk|mixed|unknown), extracted_parameters "
            "(object), alternatives (max 2 with scenario_id/confidence/label), handoff_recommended.\n"
            f"Catalog: {json.dumps(catalog, ensure_ascii=False)}\n"
            f"Selected language: {language or 'auto-detect'}. If selected, use this language value. "
            "For mixed, accept Russian and Kazakh in the same message.\n"
            f"History: {json.dumps([item.model_dump() for item in history], ensure_ascii=False)}\n"
            f"Caller: {text}"
        )
        response = await self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[{"role": "system", "content": "Return a valid JSON object without markdown."}, {"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
            timeout=self.settings.llm_timeout_seconds,
        )
        decision = RouteDecision.model_validate_json(response.choices[0].message.content or "{}")
        if decision.scenario_id not in self.by_id:
            raise ValueError("Unknown scenario returned by LLM")
        if language:
            decision.language = language
        return decision

    def _fallback_route(self, text: str, history: list[Turn], language: str | None = None) -> RouteDecision:
        normalized = text.lower()
        words = set(re.findall(r"[\w-]+", normalized, flags=re.UNICODE))
        ranked: list[tuple[int, dict]] = []
        for scenario in self.scenarios:
            score = sum(1 for keyword in scenario["keywords"] if keyword.lower() in normalized or keyword.lower() in words)
            ranked.append((score, scenario))
        ranked.sort(key=lambda item: item[0], reverse=True)
        score, selected = ranked[0]
        if score == 0 and history:
            previous = next((item for item in reversed(history) if item.role == "assistant"), None)
            if previous:
                selected = self.by_id.get("general_consultation", selected)
        language = language or self._detect_language(normalized)
        params = self._extract_parameters(text)
        alternatives = [
            Alternative(scenario_id=item["scenario_id"], confidence=round(max(0.05, min(0.85, other_score / 4)), 2), label=item["label"])
            for other_score, item in ranked[1:3]
        ]
        confidence = round(min(0.94, 0.48 + score * 0.16), 2) if score else 0.36
        handoff = selected["scenario_id"] in {"operator_handoff", "complaint_escalation", "fraud_report"}
        return RouteDecision(
            scenario_id=selected["scenario_id"], confidence=confidence,
            rationale=f"Совпали признаки: {', '.join(selected['keywords'][:3])}" if language != "kk" else f"Белгілер сәйкес келді: {', '.join(selected['keywords'][:3])}",
            language=language, extracted_parameters=params, alternatives=alternatives,
            handoff_recommended=handoff,
        )

    @staticmethod
    def _detect_language(text: str) -> str:
        kazakh = set("әіңғүұқөһә")
        has_kazakh = any(char in kazakh for char in text)
        has_cyrillic = bool(re.search(r"[а-яё]", text))
        if has_kazakh and has_cyrillic:
            return "mixed"
        if has_kazakh:
            return "kk"
        return "ru" if has_cyrillic else "unknown"

    @staticmethod
    def _extract_parameters(text: str) -> dict[str, str]:
        params: dict[str, str] = {}
        if match := re.search(r"\b(?:\+?7|8)?\s?\d{3}\s?\d{3}[ -]?\d{2}[ -]?\d{2}\b", text):
            params["phone"] = match.group(0)
        if match := re.search(r"\b\d{4}\b", text):
            params["last_four_digits"] = match.group(0)
        if match := re.search(r"\b\d+[,.]?\d*\s?(?:₸|тенге|теңге|kzt)\b", text, re.IGNORECASE):
            params["amount"] = match.group(0)
        return params
