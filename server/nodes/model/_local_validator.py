"""Saving a server the user runs: Ollama, LM Studio, or a named endpoint.

One save path for every credential whose value is a base URL (RFC-0003 §6):

- ``ollama`` / ``lmstudio``: one server each; the kind is the provider id.
- ``openai_compatible:<slug>``: any number of named endpoints (llama.cpp,
  vLLM, a LiteLLM proxy, a second Ollama host, ...); the kind is detected
  once, here, and stored.

The frontend reuses the standard ``validate_api_key`` message; its
``api_key`` field carries the Base URL, not a secret. Steps, in order:

1. Resolve the credential: the user's key, else the placeholder the vendor
   documents (``auth.placeholder_key`` in llm_defaults.json).
2. Root the URL through the OpenAI surface the runtime uses
   (:func:`services.llm.endpoints.resolve_base_url`). This is what makes a
   green panel mean a working runtime: the old probe talked to each server's
   native API, so a URL missing ``/v1`` validated and then failed every run.
3. Kind: declared, or detected from native routes by body shape.
4. Models and per-model params, per kind. Ollama and LM Studio keep their
   official SDK probes, which report the context each loaded model actually
   runs with; llama.cpp reports ``n_ctx`` on ``/props``; anything else is
   sized from vLLM's ``max_model_len``, then the LiteLLM table.
5. Persist ``{ref}_proxy`` (the resolved URL) and ``{ref}`` (key, models,
   params), register the models, broadcast.

A failure at any step writes nothing and broadcasts nothing (D5): a typo in
a re-Fetch must not take down a configuration that works.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
import lmstudio
import ollama
from core.logging import get_logger
from services.llm.config import resolve_credential
from services.llm.endpoints import SERVER_META_KEY, base_url_key, redact_url, resolve_base_url
from services.plugin.deps import get_auth_service
from services.status_broadcaster import get_status_broadcaster

logger = get_logger(__name__)

_DISPLAY_NAMES = {"ollama": "Ollama", "lmstudio": "LM Studio"}

# A save runs inside one WS request, so every step after rooting is bounded
# (the frontend waits CREDENTIAL_PROBE_REQUEST_TIMEOUT). Native routes are
# only asked once the host is known to answer, so a short timeout is enough;
# the three are asked at once, so a slow host costs one timeout, not three.
_NATIVE_TIMEOUT_SECONDS = 3.0
# The Ollama and LM Studio SDK probes. Ollama's client times out on its own;
# LM Studio's takes no timeout, so the bound is applied around both.
_SDK_PROBE_TIMEOUT_SECONDS = 10.0


def _classify_http_error(display: str, base_url: str, exc: BaseException) -> Tuple[str, str]:
    """Map a native-probe exception to (log_summary, user_message).

    Both SDKs (ollama-python, lmstudio) raise httpx errors underneath.
    Rooting has already succeeded by the time a native probe runs, so a
    failure here is about the native API, not the base URL.
    """
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        return ("timeout", f"Request to {base_url} timed out — server may be overloaded or unreachable")

    if isinstance(exc, httpx.ConnectError):
        return ("connect-refused", f"Could not reach {display} at {base_url}. Is the server running?")

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return (f"HTTP {status}", f"{display} rejected the request — server requires auth.")
        if status == 404:
            return (f"HTTP {status}", f"{display} returned 404 for its model list — check the server version.")
        if status == 429:
            return (f"HTTP {status}", f"{display} rate-limited the request — try again shortly.")
        return (f"HTTP {status}", f"{display} returned HTTP {status} — check the server logs.")

    if isinstance(exc, httpx.RequestError):
        return ("network-error", f"Network error reaching {display} at {base_url}: {exc.__class__.__name__}")

    # Unknown exception type: surface the class name + message so the
    # operator can tell what they're looking at without a stacktrace.
    return (type(exc).__name__, f"Could not reach {display}: {exc}")


def _failure(provider_ref: str, message: str) -> Dict[str, Any]:
    """Rejection envelope. Deliberately no broadcast: nothing changed (D5)."""
    return {
        "provider": provider_ref,
        "success": True,
        "valid": False,
        "message": message,
        "models": [],
        "timestamp": time.time(),
    }


def _store_failed(display: str) -> str:
    return f"Could not save {display}: the credential store did not accept the write. See the server log."


async def _restore_url_row(auth_service: Any, url_key: str, previous: Optional[str]) -> None:
    """Undo the URL-row write of a save whose key-row write failed (D5)."""
    if previous:
        restored = await auth_service.store_api_key(provider=url_key, api_key=previous, models=[])
    else:
        restored = await auth_service.remove_api_key(url_key)
    if not restored:
        logger.error("LLM server save could not restore its URL row", provider=url_key)


def _strip_v1_path(base_url: str) -> str:
    """Return ``base_url`` with a trailing ``/v1`` segment stripped.

    The stored URL is the OpenAI-compatible base (``http://host:port/v1``).
    Native APIs (Ollama's REST API, LM Studio's SDK, llama.cpp's ``/props``)
    live beside it, at the host without the OpenAI-compat suffix.
    """
    u = base_url.rstrip("/")
    if u.endswith("/v1"):
        return u[: -len("/v1")]
    return u


async def _fetch_ollama_models(base_url: str) -> List[Dict[str, Any]]:
    """List currently-loaded Ollama models with their actual params.

    Uses ``ollama.AsyncClient.ps()`` — the official "list running models"
    endpoint. Returns a typed ``ProcessResponse`` whose ``models[]``
    entries already carry every field we need as proper Pydantic
    attributes (no dict-key hunting, no Modelfile parameters parsing):

      - ``model``         — canonical name passed to ``/v1/chat/completions``
      - ``context_length``— live server-side n_ctx (this is the value
                             that produces the 400 overflow when a
                             prompt exceeds it)
      - ``details``       — typed ``ModelDetails`` (family, parameter_size,
                             quantization_level)

    If the user has models *pulled* but none currently loaded, ``ps()``
    returns an empty list — same semantics as LM Studio's
    ``list_loaded()``. The save surfaces this as the "load a model and
    click Fetch again" message, which is accurate.
    """
    host = _strip_v1_path(base_url)
    client = ollama.AsyncClient(host=host, timeout=10.0)
    try:
        running = await client.ps()
    finally:
        try:
            await client._client.aclose()
        except Exception:
            pass

    out: List[Dict[str, Any]] = []
    for m in running.models or []:
        mid = m.model or m.name
        if not mid:
            continue
        entry: Dict[str, Any] = {"id": mid}
        if m.context_length:
            entry["context_length"] = int(m.context_length)
        if m.details:
            if m.details.family:
                entry["architecture"] = m.details.family
            if m.details.parameter_size:
                entry["param_size"] = m.details.parameter_size
            if m.details.quantization_level:
                entry["quantization"] = m.details.quantization_level
            if m.details.format:
                entry["format"] = m.details.format
        out.append(entry)
    return out


async def _fetch_lmstudio_models(base_url: str) -> List[Dict[str, Any]]:
    """List currently-loaded LM Studio models with their actual params.

    Uses ``lmstudio.AsyncClient.llm.list_loaded()`` — each handle's
    ``get_info()`` returns a typed ``LlmInstanceInfo``. We read only
    SDK-typed fields (``context_length``, ``max_context_length``,
    ``vision``, ``trained_for_tool_use``, ``architecture``,
    ``params_string``); no string parsing.

    LM Studio's SDK takes ``api_host`` as ``host:port`` (no scheme, no
    path), so the stored ``http://host:port/v1`` is stripped before
    construction.
    """
    host = _strip_v1_path(base_url)
    api_host = host.split("://", 1)[-1]

    client = lmstudio.AsyncClient(api_host=api_host)
    out: List[Dict[str, Any]] = []
    async with client:
        loaded = await client.llm.list_loaded()
        for handle in loaded:
            try:
                info = await handle.get_info()
            except Exception as e:
                logger.info("[lmstudio] get_info skipped for %s: %s", getattr(handle, "identifier", "<unknown>"), type(e).__name__)
                continue
            mid = info.identifier or info.model_key
            if not mid:
                continue
            entry: Dict[str, Any] = {"id": mid}
            if info.context_length:
                entry["context_length"] = int(info.context_length)
            if info.max_context_length:
                entry["max_context_length"] = int(info.max_context_length)
            if info.vision is not None:
                entry["vision"] = bool(info.vision)
            if info.trained_for_tool_use is not None:
                entry["supports_tools"] = bool(info.trained_for_tool_use)
            if info.architecture:
                entry["architecture"] = info.architecture
            if info.params_string:
                entry["param_size"] = info.params_string
            if info.format:
                entry["format"] = info.format
            out.append(entry)
    return out


async def _get_json(client: httpx.AsyncClient, url: str) -> Any:
    """GET ``url`` and return its JSON body, or ``None`` on any failure."""
    try:
        response = await client.get(url)
        if response.status_code // 100 != 2:
            return None
        return response.json()
    except Exception:  # noqa: BLE001 — a missing route just means "not this kind"
        return None


async def _detect_kind(base_url: str, api_key: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Which server answers at ``base_url``, from its native routes.

    Each route is accepted only by body shape, never by status: LM Studio
    answers HTTP 200 to routes it does not serve. The three routes are asked
    at once; llama.cpp wins when several answer, because its server also
    mimics some Ollama routes. Returns the kind and, for llama.cpp, the
    ``/props`` body (it carries ``n_ctx``).
    """
    host = _strip_v1_path(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=_NATIVE_TIMEOUT_SECONDS, headers=headers) as client:
        props, lmstudio_models, ollama_version = await asyncio.gather(
            _get_json(client, f"{host}/props"),
            _get_json(client, f"{host}/api/v1/models"),
            _get_json(client, f"{host}/api/version"),
        )
    if isinstance(props, dict) and isinstance(props.get("default_generation_settings"), dict):
        return "llamacpp", props
    if isinstance(lmstudio_models, dict) and isinstance(lmstudio_models.get("models"), list):
        return "lmstudio", None
    if isinstance(ollama_version, dict) and isinstance(ollama_version.get("version"), str):
        return "ollama", None
    return "generic", None


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = int(value)
    return number if number > 0 else None


def _generic_params(entry: Any) -> Dict[str, Any]:
    """Size and price one model on a server that does not describe it.

    The server's own figure wins: vLLM reports ``max_model_len`` on its
    ``/models`` entries, and that is the context it enforces. Otherwise the
    LiteLLM table, by model id. Otherwise nothing, and the declared
    ``openai_compatible`` defaults apply at run time.
    """
    from services.model_registry import get_model_registry

    params: Dict[str, Any] = {}
    extra = getattr(entry, "model_extra", None) or {}
    context = _positive_int(extra.get("max_model_len"))
    if context:
        params["context_length"] = context

    spec = get_model_registry().lookup_litellm(getattr(entry, "id", "") or "")
    if spec:
        params.setdefault("context_length", _positive_int(spec.get("max_input_tokens")))
        max_out = _positive_int(spec.get("max_output_tokens"))
        # An output budget as large as the window leaves no room for the
        # prompt; drop it and let the registry derive one from the context.
        if max_out and (not params.get("context_length") or max_out < params["context_length"]):
            params["max_output_tokens"] = max_out
        for field, key in (("input_cost_per_token", "input_price_per_mtok"), ("output_cost_per_token", "output_price_per_mtok")):
            cost = spec.get(field)
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                params[key] = round(float(cost) * 1_000_000, 4)
    return {key: value for key, value in params.items() if value is not None}


async def _describe_models(
    kind: str,
    base_url: str,
    entries: List[Any],
    props: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """``{model_id: params}`` for the server, per kind (RFC-0003 D15).

    Local kinds never take LiteLLM figures: the bound that matters is the
    context the server was started with, not the model's trained maximum,
    and a local run costs nothing.
    """
    if kind in ("ollama", "lmstudio"):
        fetch = _fetch_ollama_models if kind == "ollama" else _fetch_lmstudio_models
        loaded = await asyncio.wait_for(fetch(base_url), _SDK_PROBE_TIMEOUT_SECONDS)
        return {e["id"]: {k: v for k, v in e.items() if k != "id"} for e in loaded}

    ids = [entry for entry in entries if isinstance(getattr(entry, "id", None), str) and entry.id]
    if kind == "llamacpp":
        settings = (props or {}).get("default_generation_settings") or {}
        n_ctx = _positive_int(settings.get("n_ctx"))
        return {entry.id: ({"context_length": n_ctx} if n_ctx else {}) for entry in ids}

    from services.model_registry import get_model_registry

    await get_model_registry().ensure_litellm_table()
    return {entry.id: _generic_params(entry) for entry in ids}


def _no_models_message(kind: str, display: str, base_url: str) -> str:
    if kind in ("ollama", "lmstudio"):
        return (
            f"Connected to {display} at {redact_url(base_url)}, but no models are loaded. "
            f"Load a model in {display} and click Fetch again."
        )
    return f"{display} at {redact_url(base_url)} lists no models."


async def save_llm_server(
    provider_ref: str,
    candidate_url: str,
    user_key: Optional[str],
    *,
    display: str,
    kind: Optional[str] = None,
    label: str = "",
) -> Dict[str, Any]:
    """Root, describe and persist one server. Returns the WS envelope.

    ``kind`` is passed for providers that declare it (ollama, lmstudio) and
    left ``None`` for named endpoints, which are detected once here.
    """
    try:
        api_key = resolve_credential(provider_ref, user_key)
    except ValueError:
        return _failure(provider_ref, f"No API key is available for {display}.")

    resolved = await resolve_base_url(candidate_url, api_key=api_key)
    if not resolved.ok:
        logger.warning("LLM server save failed", provider=provider_ref, reason=resolved.reason)
        return _failure(provider_ref, resolved.reason)
    base_url = resolved.base_url

    props: Optional[Dict[str, Any]] = None
    if kind is None:
        kind, props = await _detect_kind(base_url, api_key)

    try:
        model_params = await _describe_models(kind, base_url, resolved.models, props)
    except Exception as exc:  # noqa: BLE001 — SDK and httpx failures, classified below
        log_summary, message = _classify_http_error(display, redact_url(base_url), exc)
        logger.warning("LLM server model probe failed", provider=provider_ref, error=log_summary, url=redact_url(base_url))
        return _failure(provider_ref, message)

    if not model_params:
        logger.info("LLM server reachable but lists no models", provider=provider_ref, url=redact_url(base_url))
        return _failure(provider_ref, _no_models_message(kind, display, base_url))

    models = list(model_params)
    # Only the redacted form is stored here: this JSON column is not
    # encrypted, and a URL can carry userinfo. The full URL lives in the
    # encrypted ``{ref}_proxy`` row.
    server_meta = {
        "label": label or display,
        "base_url": redact_url(base_url),
        "kind": kind,
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }

    auth_service = get_auth_service()
    url_key = base_url_key(provider_ref)
    previous_url = await auth_service.get_api_key(url_key)
    # The URL row first: a key row with no URL row is exactly what the
    # runtime reports as "not configured". store_api_key reports a failed
    # write by returning False; a save it rejected is not a save.
    if not await auth_service.store_api_key(provider=url_key, api_key=base_url, models=[]):
        return _failure(provider_ref, _store_failed(display))
    if not await auth_service.store_api_key(
        provider=provider_ref,
        api_key=api_key,
        models=models,
        model_params={**model_params, SERVER_META_KEY: server_meta},
    ):
        await _restore_url_row(auth_service, url_key, previous_url)
        return _failure(provider_ref, _store_failed(display))

    # Keep the sync ``get_context_length`` / ``get_max_output_tokens``
    # lookups on the real per-model values without a DB read per call.
    from services.model_registry import get_model_registry

    registry = get_model_registry()
    registry.forget_local_models(provider_ref)
    for mid, params in model_params.items():
        if params:
            registry.register_local_model(provider_ref, mid, params)

    message = f"{len(models)} model(s) at {redact_url(base_url)}"
    await get_status_broadcaster().update_api_key_status(
        provider=provider_ref,
        valid=True,
        message=message,
        has_key=True,
        models=models,
    )
    ctx_summary = ", ".join(f"{mid}={p['context_length']}" for mid, p in model_params.items() if p.get("context_length"))
    logger.info(
        "LLM server saved",
        provider=provider_ref,
        kind=kind,
        url=redact_url(base_url),
        rewritten=resolved.rewritten,
        models=len(models),
        context=ctx_summary or "server did not report one",
    )
    return {
        "provider": provider_ref,
        "success": True,
        "valid": True,
        "models": models,
        "message": message,
        "base_url": redact_url(base_url),
        "kind": kind,
        "timestamp": time.time(),
    }


async def validate_local_llm(data: Dict[str, Any]) -> Dict[str, Any]:
    """``validate_api_key`` for ollama / lmstudio: one server, kind declared.

    Called from :meth:`nodes.model._credentials._LocalLLM.validate`.
    """
    provider = data["provider"].lower()
    base_url = (data.get("api_key") or "").strip()
    if not base_url:
        return {"success": False, "valid": False, "error": "Base URL required"}
    return await save_llm_server(
        provider,
        base_url,
        None,
        display=_DISPLAY_NAMES.get(provider, provider),
        kind=provider,
    )
