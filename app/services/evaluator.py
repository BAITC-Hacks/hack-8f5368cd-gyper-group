from typing import Any


def evaluate_prediction(prediction: dict[str, Any], expected_scenario_id: str) -> dict[str, Any]:
    """Small evaluator compatible with common scenario-routing benchmark rows."""
    selected = prediction.get("selected_scenario_id")
    return {
        "correct": selected == expected_scenario_id,
        "selected_scenario_id": selected,
        "expected_scenario_id": expected_scenario_id,
        "confidence": prediction.get("confidence", 0.0),
    }
