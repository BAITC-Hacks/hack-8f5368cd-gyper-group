from collections import deque

from schemas.router import Turn


class ConversationContext:
    def __init__(self) -> None:
        self.history: deque[Turn] = deque(maxlen=10)
        self.goal_stack: list[str] = []
        self.parameters: dict[str, str] = {}

    def add_turn(self, role: str, text: str) -> None:
        self.history.append(Turn(role=role, text=text))

    def record_route(self, scenario_id: str, parameters: dict[str, str]) -> None:
        if not self.goal_stack or self.goal_stack[-1] != scenario_id:
            self.goal_stack.append(scenario_id)
            self.goal_stack = self.goal_stack[-5:]
        self.parameters.update(parameters)

    def snapshot_for_operator(self) -> dict[str, object]:
        return {
            "history": [turn.model_dump() for turn in self.history],
            "active_goals": self.goal_stack,
            "known_parameters": self.parameters,
        }

    def reset(self) -> None:
        self.history.clear()
        self.goal_stack.clear()
        self.parameters.clear()
