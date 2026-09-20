from __future__ import annotations

import time

from app.ai.gemini_client import call_gemini
from app.ai.provider import AIResponse


class GeminiVertexProvider:
    provider_name = "gemini_vertex"

    def __init__(self, credential):
        self._credential = credential

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
        del temperature, max_tokens

        started = time.monotonic()
        text = await call_gemini(
            self._credential,
            prompt,
            model_override=model,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        return AIResponse(
            content=text,
            model=model or self._credential.default_model,
            provider=self.provider_name,
            latency_ms=latency_ms,
        )

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        del input_tokens, output_tokens
        return 0.0
