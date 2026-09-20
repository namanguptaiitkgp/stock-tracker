import base64
import json
import logging
import time

import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account as sa_module

from app.ai.credential_rotation import mark_exhausted

logger = logging.getLogger(__name__)

_vertex_token_cache: dict[int, dict] = {}


class CredentialExhaustedError(RuntimeError):
    def __init__(self, credential_id: int, message: str = ""):
        self.credential_id = credential_id
        super().__init__(message or f"Credential {credential_id} hit 429 quota limit")


def _get_vertex_token_for_credential(cred) -> str:
    cred_id = cred.id
    now = time.time()
    cached = _vertex_token_cache.get(cred_id)
    if cached and cached["expiry"] > now + 60:
        return cached["token"]

    sa_info = {
        "type": "service_account",
        "project_id": cred.project_id,
        "private_key_id": cred.private_key_id,
        "private_key": (cred.encrypted_private_key or "").replace("\\n", "\n"),
        "client_email": cred.client_email,
        "token_uri": cred.token_uri or "https://oauth2.googleapis.com/token",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    }
    creds = sa_module.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    creds.refresh(GoogleAuthRequest())
    _vertex_token_cache[cred_id] = {"token": creds.token, "expiry": now + 3500}
    return creds.token


async def call_gemini(
    credential,
    prompt: str,
    *,
    model_override: str | None = None,
    image_bytes: bytes | None = None,
    image_mime: str = "image/png",
    tools: list[dict] | None = None,
) -> str:
    model = model_override or credential.default_model

    parts: list[dict] = []
    if image_bytes:
        parts.append({
            "inline_data": {
                "mime_type": image_mime,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        })
    parts.append({"text": prompt})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        },
    }
    if tools:
        payload["tools"] = tools

    if credential.credential_type == "vertex_service_account":
        # Vertex API uses google_search; generative language API uses googleSearch
        if tools:
            normalized = []
            for t in tools:
                if "googleSearch" in t or "googleSearchRetrieval" in t:
                    normalized.append({"google_search": {}})
                else:
                    normalized.append(t)
            payload["tools"] = normalized
        token = _get_vertex_token_for_credential(credential)
        location = credential.location or "us-central1"
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{credential.project_id}/locations/{location}/"
            f"publishers/google/models/{model}:generateContent"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    elif credential.credential_type == "gemini_api_key":
        api_key = credential.encrypted_api_key
        if not api_key:
            raise ValueError(f"Credential '{credential.label}' has no API key configured")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
    else:
        raise ValueError(f"Unknown credential type: {credential.credential_type}")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            mark_exhausted(credential.id)
            raise CredentialExhaustedError(credential.id)
        if resp.status_code >= 400:
            try:
                err_body = resp.json()
            except Exception:
                err_body = {"raw": resp.text[:500]}
            raise RuntimeError(f"Gemini {resp.status_code}: {err_body}")
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return ""

    content = candidates[0].get("content", {})
    parts_out = content.get("parts", [])
    return "".join(p.get("text", "") for p in parts_out)


async def call_gemini_with_rotation(
    user_id: int,
    db,
    prompt: str,
    *,
    model_override: str | None = None,
    image_bytes: bytes | None = None,
    image_mime: str = "image/png",
    tools: list[dict] | None = None,
) -> str:
    from app.ai.credential_rotation import get_credential, get_next_credential
    from app.observability.activity import log_llm_call

    cred = await get_credential(user_id, db)
    start = time.time()
    error_class: str | None = None
    success = True
    cred_used = cred
    try:
        result = await call_gemini(
            cred, prompt,
            model_override=model_override,
            image_bytes=image_bytes,
            image_mime=image_mime,
            tools=tools,
        )
        return result
    except CredentialExhaustedError as e:
        logger.warning("Credential '%s' (id=%d) exhausted, trying next...", cred.label, cred.id)
        # Treat the first call as success=False since it 429'd.
        try:
            await log_llm_call(
                provider="gemini",
                model=model_override or getattr(cred, "default_model", None),
                user_id=user_id,
                credential_id=cred.id,
                latency_ms=int((time.time() - start) * 1000),
                success=False,
                error_class="CredentialExhaustedError",
            )
        except Exception:
            pass
        next_cred = await get_next_credential(user_id, db, after_id=cred.id)
        cred_used = next_cred
        start = time.time()
        result = await call_gemini(
            next_cred, prompt,
            model_override=model_override,
            image_bytes=image_bytes,
            image_mime=image_mime,
            tools=tools,
        )
        return result
    except Exception as e:
        error_class = type(e).__name__
        success = False
        raise
    finally:
        try:
            await log_llm_call(
                provider="gemini",
                model=model_override or getattr(cred_used, "default_model", None),
                user_id=user_id,
                credential_id=cred_used.id,
                latency_ms=int((time.time() - start) * 1000),
                success=success,
                error_class=error_class,
            )
        except Exception:
            pass


async def extract_stocks_from_image(user_id: int, db, image_bytes: bytes, image_mime: str) -> list[str]:
    prompt = """Extract all stock names, ticker symbols, or company names from this image.
Return ONLY a JSON array of strings, nothing else. Example: ["RELIANCE", "TCS", "HDFC Bank", "Infosys"]
If you can identify the NSE trading symbol, use that. Otherwise return the company name as shown.
If the image contains no stock-related information, return an empty array: []"""

    result = await call_gemini_with_rotation(user_id, db, prompt, image_bytes=image_bytes, image_mime=image_mime)
    return _parse_json_array(result)


async def resolve_stock_symbols(user_id: int, db, names: list[str]) -> dict[str, dict]:
    if not names:
        return {}

    names_str = json.dumps(names)
    prompt = f"""Map each of these stock names/symbols to their NSE (National Stock Exchange of India) trading symbol.

Input: {names_str}

Return ONLY a JSON object where each key is the original input and the value is an object with:
- "symbol": the exact NSE tradingsymbol (e.g., "RELIANCE", "TCS", "HDFCBANK", "INFY")
- "name": full company name
- "confidence": "high", "medium", or "low"
- "error": null if found, or error message if not mappable

Example:
{{"Reliance": {{"symbol": "RELIANCE", "name": "Reliance Industries Limited", "confidence": "high", "error": null}},
 "some random text": {{"symbol": null, "name": null, "confidence": "low", "error": "Could not identify as a stock"}}}}

Be strict: only return NSE-listed Indian stocks. Return the JSON object only, no markdown or explanation."""

    result = await call_gemini_with_rotation(user_id, db, prompt)
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        return {name: {"symbol": None, "name": None, "confidence": "low", "error": "Failed to parse AI response"} for name in names}


async def list_available_models(user_id: int, db) -> list[dict]:
    from app.ai.credential_rotation import get_active_credentials

    creds = await get_active_credentials(user_id, db)
    if not creds:
        return []

    cred = creds[0]

    if cred.credential_type == "vertex_service_account":
        token = _get_vertex_token_for_credential(cred)
        location = cred.location or "us-central1"
        url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{cred.project_id}/locations/{location}/"
            f"publishers/google/models"
        )
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", data.get("publisherModels", [])):
            name = m.get("name", "")
            model_id = name.split("/")[-1] if "/" in name else name
            display = m.get("displayName", model_id)
            if "gemini" in model_id.lower() or "gemini" in display.lower():
                models.append({"id": model_id, "name": display, "description": m.get("description", "")[:100]})
        return sorted(models, key=lambda x: x["id"])

    elif cred.credential_type == "gemini_api_key":
        api_key = cred.encrypted_api_key
        if not api_key:
            return []
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            model_id = m.get("name", "").replace("models/", "")
            if "gemini" in model_id.lower() and "generateContent" in str(m.get("supportedGenerationMethods", [])):
                models.append({"id": model_id, "name": m.get("displayName", model_id), "description": m.get("description", "")[:100]})
        return sorted(models, key=lambda x: x["id"])

    return []


def _parse_json_array(text: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return [str(item).strip() for item in result if item]
    except (json.JSONDecodeError, IndexError):
        pass
    return []
