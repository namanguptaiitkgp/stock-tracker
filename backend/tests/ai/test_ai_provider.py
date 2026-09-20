"""Tests for the AI provider Protocol + registry.

Skinny PR scope: only the factory routing and Gemini Vertex provider
contract are exercised. No real Gemini calls are made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.provider import AIProviderConfigError, AIResponse
from app.ai.providers.gemini_vertex import GeminiVertexProvider
from app.ai.registry import (
    DEFAULT_PROVIDER,
    PROVIDER_DEFAULTS,
    PROVIDER_REGISTRY,
    get_ai_provider,
)


def _user(settings: dict | None = None, gemini_key: str | None = "test-key", anthropic_key: str | None = None):
    """Light user stand-in — User.__init__ takes positional kw, this is simpler."""
    return SimpleNamespace(
        gemini_api_key=gemini_key,
        anthropic_api_key=anthropic_key,
        settings_json=settings or {},
    )


# ---- registry routing -------------------------------------------------------


def test_default_provider_is_gemini_vertex():
    assert DEFAULT_PROVIDER == "gemini_vertex"
    assert "gemini_vertex" in PROVIDER_REGISTRY


def test_get_ai_provider_default_returns_gemini_vertex():
    user = _user()
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = get_ai_provider(user, purpose="analysis")
    assert provider.provider_name == "gemini_vertex"


def test_get_ai_provider_screening_always_gemini():
    """Even if a user picks Anthropic for analysis, screening stays on Gemini."""
    user = _user(settings={"ai_analysis_provider": "anthropic"})
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = get_ai_provider(user, purpose="screening")
    assert provider.provider_name == "gemini_vertex"


def test_get_ai_provider_unknown_provider_raises():
    user = _user(settings={"ai_analysis_provider": "made_up_provider"})
    with pytest.raises(AIProviderConfigError, match="Unknown AI provider"):
        get_ai_provider(user, purpose="analysis")


def test_legacy_gemini_model_setting_is_honoured():
    """Existing users have `gemini_model` not `analysis_model` — must not regress."""
    user = _user(settings={"gemini_model": "gemini-2.5-pro"})
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = get_ai_provider(user, purpose="analysis")
    # The model is held internally by the provider; verify via the
    # default it would resolve when called without an override.
    assert provider._analysis_model == "gemini-2.5-pro"  # noqa: SLF001 — test inspecting impl


def test_explicit_analysis_model_wins_over_legacy_key():
    user = _user(settings={"gemini_model": "gemini-2.5-pro", "analysis_model": "gemini-2.5-flash"})
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = get_ai_provider(user, purpose="analysis")
    assert provider._analysis_model == "gemini-2.5-flash"  # noqa: SLF001


def test_provider_defaults_have_screening_and_analysis_models():
    for name, defaults in PROVIDER_DEFAULTS.items():
        assert "screening_model" in defaults, f"{name} missing screening_model"
        assert "analysis_model" in defaults, f"{name} missing analysis_model"


# ---- GeminiVertexProvider contract ------------------------------------------


def test_gemini_vertex_requires_key_or_vertex():
    """Without a key AND without a Vertex service account, init must raise."""
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=False):
        with pytest.raises(AIProviderConfigError, match="GEMINI_API_KEY"):
            GeminiVertexProvider(api_key=None, analysis_model="gemini-2.5-flash")


def test_gemini_vertex_init_with_key_only():
    """API-key-only path (no Vertex SA) succeeds."""
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=False):
        provider = GeminiVertexProvider(api_key="sk-test", analysis_model="gemini-2.5-flash")
    assert provider.provider_name == "gemini_vertex"


def test_gemini_vertex_estimate_cost_is_zero_for_now():
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = GeminiVertexProvider(api_key=None, analysis_model="gemini-2.5-flash")
    assert provider.estimate_cost(1000, 500) == 0.0


@pytest.mark.asyncio
async def test_gemini_vertex_analyze_wraps_call_gemini():
    """`analyze()` should call the existing call_gemini helper and wrap the response."""
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = GeminiVertexProvider(api_key=None, analysis_model="gemini-2.5-flash")

    async def fake_call(api_key, prompt, model, image_bytes=None, image_mime="image/png"):
        return f"echoed:{prompt[:20]}|model={model}"

    with patch("app.ai.providers.gemini_vertex.call_gemini", side_effect=fake_call):
        resp: AIResponse = await provider.analyze("hello world prompt", model="gemini-2.5-pro")

    assert resp.content.startswith("echoed:hello world prompt")
    assert resp.model == "gemini-2.5-pro"
    assert resp.provider == "gemini_vertex"
    assert resp.latency_ms >= 0
    assert resp.input_tokens == 0  # token tracking lands later


@pytest.mark.asyncio
async def test_gemini_vertex_analyze_uses_default_model_when_unspecified():
    with patch("app.ai.providers.gemini_vertex._use_vertex", return_value=True):
        provider = GeminiVertexProvider(api_key=None, analysis_model="gemini-2.5-flash")

    captured: dict[str, str] = {}

    async def fake_call(api_key, prompt, model, image_bytes=None, image_mime="image/png"):
        captured["model"] = model
        return "ok"

    with patch("app.ai.providers.gemini_vertex.call_gemini", side_effect=fake_call):
        await provider.analyze("p")
    assert captured["model"] == "gemini-2.5-flash"
