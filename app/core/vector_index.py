import re
from collections import Counter
from hashlib import blake2b
from math import log, sqrt
from typing import Any

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
_ABBREVIATION_ALIASES = {"огпо": "ogpo", "каско": "casco", "дмс": "dms"}


class VectorIndex:
    """Small, dependency-free hashed-vector index for low-latency local retrieval."""

    def __init__(self, scenarios: list[dict[str, Any]], dimensions: int = 4096) -> None:
        self.scenarios = scenarios
        self.dimensions = dimensions
        self.matrix = [self._embed(self._scenario_text(item)) for item in scenarios]
        self.tokens = [set(self._tokens(self._scenario_text(item))) for item in scenarios]
        self.slug_tokens = [set(self._tokens(item.get("slug", ""))) for item in scenarios]
        self.example_tokens = [self._example_tokens(item) for item in scenarios]
        document_frequency = Counter(token for tokens in self.tokens for token in tokens)
        self.idf = {token: log((1 + len(scenarios)) / (1 + count)) + 1 for token, count in document_frequency.items()}

    @staticmethod
    def _scenario_text(scenario: dict[str, Any]) -> str:
        fields = ("id", "title_ru", "title_kz", "description", "keywords", "examples", "not_this_if")
        return " ".join(VectorIndex._flatten(scenario.get(field, "")) for field in fields)

    @staticmethod
    def _flatten(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(VectorIndex._flatten(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(VectorIndex._flatten(item) for item in value)
        return str(value)

    @staticmethod
    def _example_tokens(scenario: dict[str, Any]) -> list[set[str]]:
        examples = scenario.get("raw_examples", scenario.get("examples", {}))
        if not isinstance(examples, dict):
            return []
        return [
            set(VectorIndex._tokens(example))
            for language_examples in examples.values()
            if isinstance(language_examples, list)
            for example in language_examples
        ]

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = text.lower().replace("_", " ")
        for source, target in _ABBREVIATION_ALIASES.items():
            normalized = normalized.replace(source, target)
        return _TOKEN_RE.findall(normalized)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokens(text)
        for token, count in Counter(tokens).items():
            index = int.from_bytes(blake2b(token.encode("utf-8"), digest_size=4).digest(), "big") % self.dimensions
            vector[index] += count
        norm = sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    def search(self, text: str, limit: int = 3) -> list[dict[str, Any]]:
        query = self._embed(text)
        query_tokens = set(self._tokens(text))
        query_weight = sum(self.idf.get(token, 1.0) for token in query_tokens)
        scores = [
            sum(left * right for left, right in zip(vector, query))
            + 3.0 * sum(self.idf.get(token, 1.0) for token in tokens & query_tokens) / max(query_weight, 1.0)
            + 2.5 * max(
                (len(example & query_tokens) / max(len(query_tokens), 1) for example in examples), default=0.0
            )
            + 3.0 * len(slug & query_tokens)
            for vector, tokens, examples, slug in zip(self.matrix, self.tokens, self.example_tokens, self.slug_tokens)
        ]
        indexes = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:limit]
        return [
            {"scenario": self.scenarios[index], "score": round(scores[index], 4)}
            for index in indexes
        ]
