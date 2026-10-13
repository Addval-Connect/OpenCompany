"""Tests for the Skill tool's search/read UX (model-robustness).

Production (CartolaTax, addval-tax): the model called search_resource
without a `path` and burned 9 activity retries on the opaque
INVALID_SKILL_RESOURCE guard. The contract now:

- search_resource WITHOUT path: skill-wide search across every declared
  reference + script, each match carrying its resource path;
- read_resource without path: SKILL_PATH_REQUIRED, teaching the shape;
- SkillRuntimeError: non-retryable at the Temporal boundary (fail fast
  back to the model).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.skill_runtime import SkillRuntimeError, execute_skill_tool


def _skill():
    return SimpleNamespace(
        instructions="Instructions for the contract skill.",
        references={
            "contrato-sesion-importacion.md": (
                "linea uno\n"
                "campos obligatorios del archivo.json: fecha, monto\n"
                "linea tres\n"
                "schema obligatorio en la seccion final\n"
            )
        },
        scripts={
            "validar.py": "def validar():\n    return 'campos obligatorios revisados'\n",
        },
    )


def _descriptors():
    return [
        {"skill_name": "contrato-sesion-importacion", "description": "El contrato.", "parameters": {}},
    ]


def _config():
    return {
        "parameters": {
            "skill_descriptors": _descriptors(),
            "agent_node_id": "agent-1",
        },
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "parent_node_id": "agent-1",
        "tool_call_id": "call-1",
    }


@pytest.mark.asyncio
async def test_search_without_path_searches_the_whole_skill():
    """The model's natural expectation: search_resource with no path
    searches every declared reference + script, and each match carries
    its resource path so the model can read_resource it next."""
    skill = _skill()
    with patch("services.skill_loader.get_skill_loader") as loader, patch(
        "services.skill_runtime._event", new=AsyncMock()
    ):
        loader.return_value.load_skill.return_value = skill
        await execute_skill_tool(
            {"action": "load", "skill_name": "contrato-sesion-importacion"},
            _config(),
        )
        result = await execute_skill_tool(
            {"action": "search_resource", "skill_name": "contrato-sesion-importacion",
             "query": "campos obligatorios"},
            _config(),
        )

    assert result["total_matches"] == 2  # one in references, one in scripts
    paths = [m["path"] for m in result["matches"]]
    assert paths == ["references/contrato-sesion-importacion.md", "scripts/validar.py"]
    assert all("campos obligatorios" in m["text"].lower() for m in result["matches"])


@pytest.mark.asyncio
async def test_search_with_path_stays_scoped():
    skill = _skill()
    with patch("services.skill_loader.get_skill_loader") as loader, patch(
        "services.skill_runtime._event", new=AsyncMock()
    ):
        loader.return_value.load_skill.return_value = skill
        await execute_skill_tool(
            {"action": "load", "skill_name": "contrato-sesion-importacion"},
            _config(),
        )
        result = await execute_skill_tool(
            {"action": "search_resource", "skill_name": "contrato-sesion-importacion",
             "path": "references/contrato-sesion-importacion.md", "query": "schema"},
            _config(),
        )
    assert result["total_matches"] == 1
    assert result["matches"][0]["path"] == "references/contrato-sesion-importacion.md"


@pytest.mark.asyncio
async def test_read_without_path_teaches_the_shape():
    skill = _skill()
    with patch("services.skill_loader.get_skill_loader") as loader, patch(
        "services.skill_runtime._event", new=AsyncMock()
    ):
        loader.return_value.load_skill.return_value = skill
        await execute_skill_tool(
            {"action": "load", "skill_name": "contrato-sesion-importacion"},
            _config(),
        )
        with pytest.raises(SkillRuntimeError, match="read_resource requires path"):
            await execute_skill_tool(
                {"action": "read_resource", "skill_name": "contrato-sesion-importacion"},
                _config(),
            )


def test_skill_runtime_error_is_non_retryable_at_the_activity_boundary():
    """Source contract: invoke_agent_skill translates SkillRuntimeError
    into a NON-RETRYABLE ApplicationError — production burned 9 activity
    retries (~40s of wall time) on a deterministic model error."""
    import inspect

    from services.temporal import agent_activities

    source = inspect.getsource(agent_activities.invoke_agent_skill)
    assert "ApplicationError" in source
    assert "non_retryable=True" in source
    assert "except SkillRuntimeError" in source
