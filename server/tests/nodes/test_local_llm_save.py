"""RFC-0003 §6 save path: Ollama, LM Studio and named endpoints.

AG6 (a failed save changes nothing), AG13 (kind detection by body shape)
and AG14 (per-kind metadata; LiteLLM never feeds a local kind). HTTP is
mocked with respx; the Ollama / LM Studio SDK probes are replaced, since
what matters here is that they are still the ones called.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

import nodes.model._local_validator as lv

REF = "openai_compatible:home"


def _models(*ids: str, **extra: Any) -> Dict[str, Any]:
    return {"object": "list", "data": [{"id": mid, "object": "model", **extra.get(mid, {})} for mid in ids]}


class FakeAuth:
    """In-memory stand-in for AuthService's API-key surface."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.stored: List[str] = []
        # Providers whose write the store rejects, as AuthService does on a
        # database error: it logs and returns False.
        self.rejects: set = set()

    async def store_api_key(self, provider, api_key, models, session_id="default", model_params=None):
        if provider in self.rejects:
            return False
        self.stored.append(provider)
        self.rows[provider] = {"key": api_key, "models": list(models), "model_params": model_params or {}}
        return True

    async def get_api_key(self, provider, session_id="default") -> Optional[str]:
        row = self.rows.get(provider)
        return row["key"] if row else None

    async def remove_api_key(self, provider, session_id="default") -> bool:
        self.rows.pop(provider, None)
        return True


@pytest.fixture
def auth(monkeypatch) -> FakeAuth:
    fake = FakeAuth()
    monkeypatch.setattr(lv, "get_auth_service", lambda: fake)
    return fake


@pytest.fixture
def broadcaster(monkeypatch) -> MagicMock:
    fake = MagicMock()
    fake.update_api_key_status = AsyncMock()
    monkeypatch.setattr(lv, "get_status_broadcaster", lambda: fake)
    return fake


@pytest.fixture
def registry(tmp_path, monkeypatch):
    import services.model_registry as mr

    monkeypatch.setattr(mr, "_local_models_path", lambda: tmp_path / "local_models.json")
    monkeypatch.setattr(mr, "_litellm_cache_path", lambda: tmp_path / "litellm_models.json")
    svc = mr.ModelRegistryService()
    svc._load_llm_defaults()
    svc.lookup_litellm = MagicMock(wraps=svc.lookup_litellm)
    svc.ensure_litellm_table = AsyncMock()
    monkeypatch.setattr(mr, "get_model_registry", lambda: svc)
    return svc


class TestKindDetection:
    """Each native route counts only by body shape (LM Studio answers 200 to anything)."""

    LM_STUDIO_ERROR = {"error": "Unexpected endpoint or method. Returning 200 anyway"}

    @respx.mock
    async def test_llamacpp_is_recognized_by_props(self):
        props = {"default_generation_settings": {"n_ctx": 4096}}
        respx.get("http://host:8080/props").mock(return_value=httpx.Response(200, json=props))

        assert await lv._detect_kind("http://host:8080/v1", "k") == ("llamacpp", props)

    @respx.mock
    async def test_lm_studio_is_recognized_despite_answering_200_everywhere(self):
        respx.get("http://host:1234/props").mock(return_value=httpx.Response(200, json=self.LM_STUDIO_ERROR))
        respx.get("http://host:1234/api/v1/models").mock(return_value=httpx.Response(200, json={"models": []}))

        assert await lv._detect_kind("http://host:1234/v1", "k") == ("lmstudio", None)

    @respx.mock
    async def test_a_200_with_an_error_body_is_not_ollama(self):
        for path in ("/props", "/api/v1/models", "/api/version"):
            respx.get(f"http://host:1234{path}").mock(return_value=httpx.Response(200, json=self.LM_STUDIO_ERROR))

        assert await lv._detect_kind("http://host:1234/v1", "k") == ("generic", None)

    @respx.mock
    async def test_ollama_is_recognized_by_its_version_route(self):
        respx.get("http://host:11434/props").mock(return_value=httpx.Response(404))
        respx.get("http://host:11434/api/v1/models").mock(return_value=httpx.Response(404))
        respx.get("http://host:11434/api/version").mock(return_value=httpx.Response(200, json={"version": "0.12.0"}))

        assert await lv._detect_kind("http://host:11434/v1", "k") == ("ollama", None)

    @respx.mock
    async def test_anything_else_is_generic(self):
        respx.route(host="host").mock(return_value=httpx.Response(404))

        assert await lv._detect_kind("http://host:8000/v1", "k") == ("generic", None)


class TestFailedSaveChangesNothing:
    @respx.mock
    async def test_an_unrooted_url_writes_and_broadcasts_nothing(self, auth, broadcaster, registry):
        respx.get("http://host/models").mock(return_value=httpx.Response(404))
        respx.get("http://host/v1/models").mock(return_value=httpx.Response(404))

        result = await lv.save_llm_server(REF, "http://host", None, display="home", label="home")

        assert result["valid"] is False
        assert "No OpenAI-compatible API" in result["message"]
        assert auth.stored == []
        broadcaster.update_api_key_status.assert_not_awaited()

    @respx.mock
    async def test_a_server_with_nothing_loaded_writes_nothing(self, auth, broadcaster, registry, monkeypatch):
        respx.get("http://host:11434/models").mock(return_value=httpx.Response(404))
        respx.get("http://host:11434/v1/models").mock(return_value=httpx.Response(200, json=_models("llama3:latest")))
        monkeypatch.setattr(lv, "_fetch_ollama_models", AsyncMock(return_value=[]))

        result = await lv.validate_local_llm({"provider": "ollama", "api_key": "http://host:11434"})

        assert result["valid"] is False
        assert "no models are loaded" in result["message"]
        assert auth.stored == []
        broadcaster.update_api_key_status.assert_not_awaited()

    @staticmethod
    def _llamacpp_at(base: str) -> None:
        respx.get(f"{base}/models").mock(return_value=httpx.Response(200, json=_models("model.gguf")))
        respx.get(f"{base}/props").mock(
            return_value=httpx.Response(200, json={"default_generation_settings": {"n_ctx": 8192}})
        )

    @respx.mock
    async def test_a_rejected_key_row_puts_the_old_url_back(self, auth, broadcaster, registry):
        auth.rows[f"{REF}_proxy"] = {"key": "http://old:8080", "models": [], "model_params": {}}
        auth.rejects.add(REF)
        self._llamacpp_at("http://host:8080")

        result = await lv.save_llm_server(REF, "http://host:8080", None, display="llama", label="llama")

        assert result["valid"] is False
        assert "did not accept the write" in result["message"]
        assert auth.rows[f"{REF}_proxy"]["key"] == "http://old:8080"
        assert REF not in auth.rows
        assert registry.get_model_info("model.gguf", REF) is None
        broadcaster.update_api_key_status.assert_not_awaited()

    @respx.mock
    async def test_a_rejected_first_save_leaves_no_url_row(self, auth, broadcaster, registry):
        auth.rejects.add(REF)
        self._llamacpp_at("http://host:8080")

        result = await lv.save_llm_server(REF, "http://host:8080", None, display="llama", label="llama")

        assert result["valid"] is False
        assert auth.rows == {}
        broadcaster.update_api_key_status.assert_not_awaited()


class TestSaveByKind:
    @respx.mock
    async def test_ollama_keeps_its_sdk_probe_and_stores_both_rows(self, auth, broadcaster, registry, monkeypatch):
        respx.get("http://host:11434/models").mock(return_value=httpx.Response(404))
        respx.get("http://host:11434/v1/models").mock(return_value=httpx.Response(200, json=_models("llama3:latest")))
        probe = AsyncMock(return_value=[{"id": "llama3:latest", "context_length": 4096}])
        monkeypatch.setattr(lv, "_fetch_ollama_models", probe)

        result = await lv.validate_local_llm({"provider": "ollama", "api_key": "http://host:11434"})

        assert result["valid"] is True
        probe.assert_awaited_once_with("http://host:11434/v1")
        # The URL row first: a key row without one reads as "not configured".
        assert auth.stored == ["ollama_proxy", "ollama"]
        assert auth.rows["ollama_proxy"]["key"] == "http://host:11434/v1"
        row = auth.rows["ollama"]
        assert row["key"] == "ollama"  # the documented placeholder, resolved from llm_defaults.json
        assert row["models"] == ["llama3:latest"]
        assert row["model_params"]["llama3:latest"] == {"context_length": 4096}
        assert row["model_params"]["_endpoint"]["kind"] == "ollama"
        assert registry.get_context_length("llama3:latest", "ollama") == 4096
        registry.lookup_litellm.assert_not_called()
        broadcaster.update_api_key_status.assert_awaited_once()

    @respx.mock
    async def test_llamacpp_is_sized_from_props_not_litellm(self, auth, broadcaster, registry):
        respx.get("http://host:8080/models").mock(return_value=httpx.Response(200, json=_models("model.gguf")))
        respx.get("http://host:8080/props").mock(
            return_value=httpx.Response(200, json={"default_generation_settings": {"n_ctx": 8192}})
        )

        result = await lv.save_llm_server(REF, "http://host:8080", None, display="llama", label="llama")

        assert result["valid"] is True and result["kind"] == "llamacpp"
        assert auth.rows[f"{REF}_proxy"]["key"] == "http://host:8080"
        assert auth.rows[REF]["key"] == "sk-no-key-required"
        assert auth.rows[REF]["model_params"]["model.gguf"] == {"context_length": 8192}
        registry.lookup_litellm.assert_not_called()

    @respx.mock
    async def test_generic_prefers_the_servers_context_then_litellm(self, auth, broadcaster, registry):
        respx.get("http://vllm:8000/models").mock(return_value=httpx.Response(404))
        respx.get("http://vllm:8000/v1/models").mock(
            return_value=httpx.Response(
                200,
                json=_models("Qwen/Qwen3-8B", "gpt-4o", **{"Qwen/Qwen3-8B": {"max_model_len": 32768}}),
            )
        )
        for path in ("/props", "/api/v1/models", "/api/version"):
            respx.get(f"http://vllm:8000{path}").mock(return_value=httpx.Response(404))
        registry._litellm = {
            "gpt-4o": {
                "max_input_tokens": 128000,
                "max_output_tokens": 16384,
                "input_cost_per_token": 2.5e-06,
                "output_cost_per_token": 1e-05,
            }
        }

        result = await lv.save_llm_server(REF, "http://vllm:8000", "sk-user", display="vllm", label="vllm")

        assert result["valid"] is True and result["kind"] == "generic"
        params = auth.rows[REF]["model_params"]
        assert params["Qwen/Qwen3-8B"] == {"context_length": 32768}
        assert params["gpt-4o"] == {
            "context_length": 128000,
            "max_output_tokens": 16384,
            "input_price_per_mtok": 2.5,
            "output_price_per_mtok": 10.0,
        }
        assert auth.rows[REF]["key"] == "sk-user"
        assert registry.get_context_length("gpt-4o", REF) == 128000
