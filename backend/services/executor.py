import json
import time
from pathlib import Path

from schemas.router import RouteDecision


class ScenarioExecutor:
    def __init__(self) -> None:
        base_path = Path(__file__).resolve().parents[1] / "data"
        self.scenarios = {item["scenario_id"]: item for item in json.loads((base_path / "scenarios.json").read_text(encoding="utf-8"))}
        self.mock_data = json.loads((base_path / "mock_backend.json").read_text(encoding="utf-8"))

    async def execute(self, decision: RouteDecision) -> tuple[str, float]:
        started = time.perf_counter()
        scenario = self.scenarios[decision.scenario_id]
        template = scenario["response_kk"] if decision.language == "kk" else scenario["response_ru"]
        response = template.format(**self.mock_data, **decision.extracted_parameters)
        return response, (time.perf_counter() - started) * 1000
