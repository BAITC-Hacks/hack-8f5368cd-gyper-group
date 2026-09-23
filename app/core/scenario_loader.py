import json
from pathlib import Path
from typing import Any


class ScenarioLoader:
    """Loads demo assets while allowing deployments to provide richer JSON files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def load_json(self, filename: str, default: Any) -> Any:
        path = self.data_dir / filename
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError) as error:
            raise RuntimeError(f"Cannot load {path}: {error}") from error

    def load_scenarios(self) -> list[dict[str, Any]]:
        payload = self.load_json("scenarios.json", [])
        scenarios = payload.get("scenarios") if isinstance(payload, dict) else payload
        if not isinstance(scenarios, list) or not scenarios:
            raise RuntimeError("scenarios.json must contain a non-empty 'scenarios' array")
        return [self._normalize_scenario(scenario) for scenario in scenarios]

    @staticmethod
    def _normalize_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
        examples = scenario.get("examples", {})
        example_text = " ".join(
            text for language_examples in examples.values() for text in language_examples
        ) if isinstance(examples, dict) else str(examples)
        return {
            **scenario,
            "id": scenario["scenario_id"],
            "title_ru": scenario.get("name", scenario["scenario_id"]),
            "title_kz": scenario.get("name", scenario["scenario_id"]),
            "keywords": " ".join(
                str(value) for value in (scenario.get("slug"), scenario.get("domain"), scenario.get("category"))
                if value
            ),
            "raw_examples": examples,
            "examples": example_text,
        }

    def load_assets(self) -> dict[str, Any]:
        return {
            "knowledge_base": self.load_json("knowledge_base.json", {}),
            "mock_backend": self.load_json("mock_backend.json", {}),
            "dialogs": self.load_json("dialogs_sample.json", []),
            "actions": self.load_json("actions.json", {}),
            "slots": self.load_json("slots.json", {}),
            "scenario_catalog": self.load_json("scenarios.json", {}),
        }
