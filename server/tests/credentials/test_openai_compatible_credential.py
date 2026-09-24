"""RFC-0003 D13 / AG15: named OpenAI-compatible endpoints as credentials.

Adding and refreshing go through ``validate_api_key``; removing through
``delete_api_key``; the panel's list rides the catalogue. Storage is the
real encrypted credentials DB (``auth_service`` fixture) wherever rows
matter; the save path itself is covered in tests/nodes/test_local_llm_save.py.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nodes.model import _credentials as creds
from nodes.model._credentials import OpenAICompatibleCredential

pytestmark = pytest.mark.credentials

REF = "openai_compatible:home-vllm"


@pytest.fixture
def auth(auth_service, monkeypatch):
    monkeypatch.setattr("services.plugin.deps.get_auth_service", lambda: auth_service)
    return auth_service


@pytest.fixture
def save(monkeypatch) -> AsyncMock:
    fake = AsyncMock(return_value={"success": True, "valid": True})
    monkeypatch.setattr("nodes.model._local_validator.save_llm_server", fake)
    return fake


async def _store_endpoint(auth, ref: str, url: str, key: str, label: str, models=("m1",)) -> None:
    await auth.store_api_key(provider=f"{ref}_proxy", api_key=url, models=[])
    await auth.store_api_key(
        provider=ref,
        api_key=key,
        models=list(models),
        model_params={"_endpoint": {"label": label, "base_url": url.split("@")[-1], "kind": "generic"}},
    )


class TestAdd:
    async def test_the_label_becomes_the_slug_of_the_reference(self, auth, save):
        await OpenAICompatibleCredential.validate(
            {"api_key": "http://host:8000", "openai_compatible_label": "Home vLLM", "openai_compatible_api_key": "sk-1"}
        )

        save.assert_awaited_once_with(REF, "http://host:8000", "sk-1", display="Home vLLM", label="Home vLLM")

    async def test_without_a_label_the_slug_comes_from_the_host(self, auth, save):
        await OpenAICompatibleCredential.validate({"api_key": "http://localhost:8080"})

        ref, url, key = save.await_args.args
        assert (ref, url, key) == ("openai_compatible:localhost-8080", "http://localhost:8080", None)

    async def test_a_slug_fits_the_provider_column_with_its_url_suffix(self, auth, save):
        await OpenAICompatibleCredential.validate({"api_key": "http://h", "openai_compatible_label": "a very long endpoint label indeed"})

        ref = save.await_args.args[0]
        assert len(f"{ref}_proxy") <= 50

    async def test_an_existing_label_is_rejected_not_overwritten(self, auth, save):
        await _store_endpoint(auth, REF, "http://host:8000/v1", "sk-old", "Home vLLM")

        result = await OpenAICompatibleCredential.validate({"api_key": "http://other", "openai_compatible_label": "home vllm"})

        assert result["valid"] is False and "already exists" in result["message"]
        save.assert_not_awaited()

    async def test_a_label_with_no_letter_or_digit_is_rejected(self, auth, save):
        result = await OpenAICompatibleCredential.validate({"api_key": "http://h", "openai_compatible_label": "!!!"})

        assert result["valid"] is False
        save.assert_not_awaited()


class TestRefresh:
    async def test_uses_the_stored_url_and_key_not_what_the_panel_sent(self, auth, save):
        await _store_endpoint(auth, REF, "http://user:pw@host:8000/v1", "sk-stored", "Home vLLM")

        await OpenAICompatibleCredential.validate({"api_key": "http://host:8000/v1", "ref": REF})

        save.assert_awaited_once_with(
            REF, "http://user:pw@host:8000/v1", "sk-stored", display="Home vLLM", label="Home vLLM"
        )

    @pytest.mark.parametrize("ref", ["openai_compatible:gone", "ollama", "openai_compatible:Bad_Slug"])
    async def test_an_unknown_or_malformed_reference_is_rejected(self, auth, save, ref):
        result = await OpenAICompatibleCredential.validate({"api_key": "http://h", "ref": ref})

        assert result["valid"] is False
        save.assert_not_awaited()


class TestCatalogue:
    async def test_lists_saved_endpoints_and_marks_the_provider_stored(self, auth):
        await _store_endpoint(auth, REF, "http://host:8000/v1", "sk-1", "Home vLLM", models=("a", "b"))
        await _store_endpoint(auth, "openai_compatible:lab", "http://lab:8080", "sk-no-key-required", "Lab")
        await auth.store_api_key(provider="ollama", api_key="ollama", models=["x"])

        extras = await OpenAICompatibleCredential.catalogue_extras()

        assert extras["stored"] is True
        assert extras["endpoints"] == [
            {"ref": REF, "label": "Home vLLM", "base_url": "http://host:8000/v1", "kind": "generic", "model_count": 2},
            {"ref": "openai_compatible:lab", "label": "Lab", "base_url": "http://lab:8080", "kind": "generic", "model_count": 1},
        ]

    async def test_no_endpoints_means_not_stored(self, auth):
        assert await OpenAICompatibleCredential.catalogue_extras() == {"stored": False, "endpoints": []}

    async def test_the_catalogue_handler_merges_the_extras(self, auth, monkeypatch):
        import routers.websocket as ws

        await _store_endpoint(auth, REF, "http://host:8000/v1", "sk-1", "Home vLLM")
        monkeypatch.setattr(ws.container, "auth_service", lambda: auth)

        catalogue = await ws.handle_get_credential_catalogue({}, SimpleNamespace())

        entry = next(p for p in catalogue["providers"] if p["id"] == "openai_compatible")
        assert entry["stored"] is True
        assert [e["ref"] for e in entry["endpoints"]] == [REF]


class TestDelete:
    async def test_deleting_an_endpoint_removes_its_url_row_too(self, auth, monkeypatch):
        from services.credentials import handlers

        await _store_endpoint(auth, REF, "http://host:8000/v1", "sk-1", "Home vLLM")
        broadcaster = MagicMock()
        broadcaster.update_api_key_status = AsyncMock()
        broadcaster.broadcast_credential_event = AsyncMock()
        monkeypatch.setattr(handlers.container, "auth_service", lambda: auth)
        monkeypatch.setattr(handlers, "get_status_broadcaster", lambda: broadcaster)

        await handlers.handle_delete_api_key({"provider": REF}, SimpleNamespace())

        assert await auth.get_api_key(REF) is None
        assert await auth.get_api_key(f"{REF}_proxy") is None
        broadcaster.broadcast_credential_event.assert_awaited_once()


def test_the_credential_is_registered_for_dispatch():
    from services.plugin.credential import CREDENTIAL_REGISTRY

    assert CREDENTIAL_REGISTRY["openai_compatible"] is creds.OpenAICompatibleCredential
