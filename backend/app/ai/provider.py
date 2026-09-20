"""AI provider abstraction.

Every backend (Gemini Vertex, Anthropic, OpenAI, ...) implements this
Protocol so callers don't import vendor SDKs directly. The factory in
`app.ai.registry.get_ai_provider` reads `users.settings_json` to decide
which implementation to return.

Skinny PR scope: only `GeminiVertexProvider` is implemented today.
Cost / token tracking and per-user budget enforcement land in a
follow-up alongside the `ai_usage_log` table.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class AIProviderConfigError(RuntimeError):
    """Raised when a provider can't be instantiated (missing key, etc.)."""


@dataclass
class AIResponse:
    content: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    structured: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class AIProvider(Protocol):
    """Every AI backend implements this interface."""

    provider_name: str

    async def analyze(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 8192,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
    ) -> AIResponse:
        """Single deep-analysis request. Returns the raw text plus metadata."""
        ...

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """USD cost estimate for a request of the given size. 0.0 if unknown."""
        ...
