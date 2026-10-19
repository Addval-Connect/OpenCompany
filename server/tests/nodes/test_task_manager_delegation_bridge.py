from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from nodes.tool.task_manager import _execute_task_manager
from services.plugin import NodeContext


def _config():
    return {
        "workflow_id": "wf-1", "execution_id": "exec-1", "parent_node_id": "lead-1",
        "ai_service": object(), "database": object(),
        "nodes": [
            {"id": "lead-1", "type": "orchestrator_agent", "data": {}},
            {"id": "child-1", "type": "aiAgent", "data": {"label": "Researcher"}},
        ],
        "edges": [{"source": "child-1", "target": "lead-1", "targetHandle": "input-teammates"}],
    }


@pytest.mark.asyncio
async def test_assign_starts_legacy_child_with_precreated_task_id():
    service = SimpleNamespace(assign_durable_task=AsyncMock(return_value={
        "id": "task-1", "team_id": "team-1", "status": "queued",
    }))
    execute_child = AsyncMock(return_value={"success": True, "status": "delegated", "task_id": "task-1"})

    with patch("services.agent_team.get_agent_team_service", return_value=service), patch(
        "services.handlers.tools._execute_delegated_agent", execute_child
    ):
        result = await _execute_task_manager({
            "operation": "assign_task", "title": "Research", "mission": "Find evidence",
            "assignee_node_id": "child-1", "context": {"topic": "queues"},
        }, _config())

    service.assign_durable_task.assert_awaited_once()
    execute_child.assert_awaited_once()
    assert execute_child.await_args.kwargs["precreated_task_id"] == "task-1"
    assert execute_child.await_args.args[0]["task"] == "Find evidence"
    assert result["delegation"]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_assign_without_legacy_services_returns_temporal_envelope_only():
    service = SimpleNamespace(assign_durable_task=AsyncMock(return_value={
        "id": "task-2", "team_id": "team-1", "status": "queued",
    }))
    config = _config()
    config.pop("ai_service")
    config.pop("database")

    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager({
            "operation": "assign_task", "title": "Research", "mission": "Find evidence",
            "assignee_node_id": "child-1",
        }, config)

    assert result["delegation"] is None
    assert result["delegation_request"]["team_task_id"] == "task-2"


@pytest.mark.asyncio
async def test_accept_infers_the_only_submitted_task_and_revision():
    submitted = {"id": "task-submitted", "revision": 4, "status": "submitted"}
    service = SimpleNamespace(
        list_durable_tasks=AsyncMock(return_value=[submitted]),
        mutate_durable_task=AsyncMock(return_value={**submitted, "revision": 5, "status": "accepted"}),
    )
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager({"operation": "accept_task"}, _config())

    assert result["task"]["status"] == "accepted"
    service.mutate_durable_task.assert_awaited_once_with(
        workflow_id="wf-1", team_lead_node_id="lead-1", execution_id="exec-1",
        task_id="task-submitted", revision=4, operation="accept",
    )


@pytest.mark.asyncio
async def test_accept_never_guesses_when_multiple_tasks_are_submitted():
    service = SimpleNamespace(list_durable_tasks=AsyncMock(return_value=[
        {"id": "one", "revision": 1}, {"id": "two", "revision": 2},
    ]))
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        with pytest.raises(ValueError, match="call list_tasks or get_task first"):
            await _execute_task_manager({"operation": "accept_task"}, _config())


@pytest.mark.asyncio
async def test_reassign_returns_delegation_request_for_the_new_assignee():
    """reassign moves the row to queued, and nothing sweeps queued rows —
    the scheduling envelope is the ONLY runner. Without it the mutation
    flipped the DB row and the work silently never re-ran."""
    service = SimpleNamespace(
        mutate_durable_task=AsyncMock(return_value={
            "id": "task-3", "revision": 6, "status": "queued",
            "assigned_to": "child-1", "mission": "Find evidence",
            "context": {"topic": "queues"},
        }),
    )
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager({
            "operation": "reassign_task", "task_id": "task-3",
            "expected_revision": 5, "assignee_node_id": "child-1",
        }, _config())

    assert result["task"]["status"] == "queued"
    envelope = result["delegation_request"]
    assert envelope["team_task_id"] == "task-3"
    assert envelope["assignee_node_id"] == "child-1"
    assert envelope["delegate_name"]
    assert envelope["task"] == "Find evidence"
    assert envelope["context"] == {"topic": "queues"}


@pytest.mark.asyncio
async def test_retry_returns_delegation_request_for_the_current_assignee():
    row = {
        "id": "task-4", "revision": 2, "status": "failed",
        "assigned_to": "child-1", "mission": "Find evidence", "context": {},
    }
    service = SimpleNamespace(
        get_durable_task=AsyncMock(return_value=row),
        mutate_durable_task=AsyncMock(return_value={
            **row, "revision": 3, "status": "queued",
        }),
    )
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager(
            {"operation": "retry_task", "task_id": "task-4"}, _config()
        )

    envelope = result["delegation_request"]
    assert envelope["team_task_id"] == "task-4"
    assert envelope["assignee_node_id"] == "child-1"
    assert envelope["task"] == "Find evidence"


@pytest.mark.asyncio
async def test_accept_returns_no_delegation_request():
    submitted = {"id": "task-5", "revision": 4, "status": "submitted"}
    service = SimpleNamespace(
        list_durable_tasks=AsyncMock(return_value=[submitted]),
        mutate_durable_task=AsyncMock(
            return_value={**submitted, "revision": 5, "status": "accepted"}
        ),
    )
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager({"operation": "accept_task"}, _config())

    assert "delegation_request" not in result


@pytest.mark.asyncio
async def test_list_tasks_can_include_prior_executions():
    service = SimpleNamespace(list_durable_task_history=AsyncMock(return_value=[
        {"id": "old-task", "status": "accepted", "team_execution_id": "exec-old"},
    ]))
    with patch("services.agent_team.get_agent_team_service", return_value=service):
        result = await _execute_task_manager(
            {"operation": "list_tasks", "include_history": True}, _config()
        )

    assert result["tasks"][0]["team_execution_id"] == "exec-old"
    service.list_durable_task_history.assert_awaited_once_with(
        workflow_id="wf-1", team_lead_node_id="lead-1", status=None
    )


# ---------------------------------------------------------------------------
# Model-robustness: small models mangle the assignee id and send `context`
# as prose. The resolver degrades gracefully instead of burning the lead's
# iterations (observed: 4-5 retry loops per assign in production).
# ---------------------------------------------------------------------------


def _two_teammate_config():
    return {
        "workflow_id": "wf-1", "execution_id": "exec-1", "parent_node_id": "lead-1",
        "ai_service": None, "database": None,
        "nodes": [
            {"id": "lead-1", "type": "orchestrator_agent", "data": {}},
            {"id": "b9a36cc3f2f84605b2ee1e4d453f739c:task_agent:1", "type": "task_agent", "data": {"label": "A3 — Consolida Informacion"}},
            {"id": "b9a36cc3f2f84605b2ee1e4d453f739c:tool_agent:1", "type": "tool_agent", "data": {"label": "A4 — Importa a Odoo"}},
        ],
        "edges": [
            {"source": "b9a36cc3f2f84605b2ee1e4d453f739c:task_agent:1", "target": "lead-1", "targetHandle": "input-teammates"},
            {"source": "b9a36cc3f2f84605b2ee1e4d453f739c:tool_agent:1", "target": "lead-1", "targetHandle": "input-teammates"},
        ],
    }


@pytest.mark.asyncio
async def test_assignee_resolves_from_mangled_short_prefix():
    """The observed production shape: the model dropped the workflow-prefixed
    head of the node id ("8:task_agent:1"). The stable TAIL still resolves."""
    service = SimpleNamespace(assign_durable_task=AsyncMock(return_value={
        "id": "task-1", "team_id": "team-1", "status": "queued",
    }))
    with patch("services.agent_team.get_agent_team_service", return_value=service), patch(
        "services.handlers.tools._execute_delegated_agent", AsyncMock()
    ):
        result = await _execute_task_manager({
            "operation": "assign_task", "title": "T", "mission": "M",
            "assignee_node_id": "8:task_agent:1",
        }, _two_teammate_config())
    assert result["task"]["id"] == "task-1"


@pytest.mark.asyncio
async def test_assignee_resolves_from_roster_label():
    service = SimpleNamespace(assign_durable_task=AsyncMock(return_value={
        "id": "task-2", "team_id": "team-1", "status": "queued",
    }))
    with patch("services.agent_team.get_agent_team_service", return_value=service), patch(
        "services.handlers.tools._execute_delegated_agent", AsyncMock()
    ):
        result = await _execute_task_manager({
            "operation": "assign_task", "title": "T", "mission": "M",
            "assignee_node_id": "a4 — importa a odoo",
        }, _two_teammate_config())
    assert result["task"]["id"] == "task-2"


@pytest.mark.asyncio
async def test_ambiguous_tail_still_errors_instead_of_guessing():
    """Two teammates of the same type share a tail — the fallback must
    degrade to the exact-match error, never pick one silently."""
    from nodes.tool.task_manager import _resolve_teammate

    config = _two_teammate_config()
    config["nodes"].append({
        "id": "otherwf:task_agent:1", "type": "task_agent", "data": {"label": "Otro A3"},
    })
    config["edges"].append({
        "source": "otherwf:task_agent:1", "target": "lead-1", "targetHandle": "input-teammates",
    })
    with pytest.raises(ValueError, match="must resolve to exactly one"):
        _resolve_teammate(config, {"assignee_node_id": "8:task_agent:1"})


def test_task_manager_params_coerce_prose_context_to_object():
    """`context`/`acceptance_criteria` arrive as prose from small models;
    wrap the string instead of failing the whole call."""
    from nodes.tool.task_manager import TaskManagerParams

    params = TaskManagerParams(operation="assign_task", context="Prueba de conectividad.")
    assert params.context == {"context": "Prueba de conectividad."}
    params2 = TaskManagerParams(operation="assign_task", acceptance_criteria="OK o KO con detalle.")
    assert params2.acceptance_criteria == {"acceptance_criteria": "OK o KO con detalle."}
    # dict input passes through untouched
    params3 = TaskManagerParams(operation="assign_task", context={"motivo": "x"})
    assert params3.context == {"motivo": "x"}


# ---------------------------------------------------------------------------
# Operation inference (production 2026-10-19, CartolaTax): the model sent
# assign-shaped calls (title/mission/assignee_node_id) WITHOUT `operation`.
# They silently degraded to the list_tasks default, created nothing, and the
# mangled tool response hid the mistake — the coordinator concluded "the
# Task Manager is broken". An assign-shaped call must infer assign_task; an
# explicit operation always wins.
# ---------------------------------------------------------------------------


def test_assign_shaped_params_without_operation_infer_assign_task():
    from nodes.tool.task_manager import TaskManagerParams

    params = TaskManagerParams(
        title="Visado sincronización", mission="Pre-valida en solo lectura",
        assignee_node_id="wf:tool_agent:1",
    )
    assert params.operation == "assign_task"


def test_explicit_operation_wins_over_shape_inference():
    from nodes.tool.task_manager import TaskManagerParams

    params = TaskManagerParams(
        operation="list_tasks", title="T", mission="M",
        assignee_node_id="wf:tool_agent:1",
    )
    assert params.operation == "list_tasks"


def test_unshaped_params_without_operation_keep_the_list_default():
    from nodes.tool.task_manager import TaskManagerParams

    assert TaskManagerParams(include_history=True).operation == "list_tasks"
    # mission alone (no assignee) is not assign-shaped
    assert TaskManagerParams(mission="solo texto").operation == "list_tasks"


@pytest.mark.asyncio
async def test_tool_call_without_operation_assigns_through_the_real_validation_path():
    """The full execute_as_tool pipeline (Temporal per-type activity path):
    an assign-shaped call without `operation` must reach the operation as
    assign_task, and the flat Output — which declares its own `success`
    field — must reach the LLM UNMANGLED (previously it collapsed to
    {"result": null})."""
    from nodes.tool.task_manager import TaskManagerNode

    flat = {
        "success": True, "operation": "assign_task",
        "task": {"id": "task-x", "team_id": "team-1", "status": "queued"},
        "delegation": None,
        "delegation_request": {"team_task_id": "task-x"},
    }
    captured: Dict[str, Any] = {}

    async def fake_execute(args, config):
        captured.update(args)
        return flat

    node = TaskManagerNode()
    with patch("nodes.tool.task_manager._execute_task_manager", fake_execute):
        result = await node.execute_as_tool(
            {
                "title": "Visado sincronización contable log 1546",
                "mission": "Pre-valida en solo lectura",
                "assignee_node_id": "wf:tool_agent:1",
                "context": {"modo_visado": True},
            },
            {},
            NodeContext(node_id="wf:taskManager:1", node_type="taskManager", raw={}),
        )

    assert captured["operation"] == "assign_task"
    assert result == flat  # flat passthrough — no envelope re-wrap


@pytest.mark.asyncio
async def test_flat_output_with_success_key_reaches_the_llm_unmangled():
    """The double-envelope bug: ToolNode._wrap_success returns the flat
    Output dict, but execute_as_tool re-checked `"success" not in envelope`
    — a flat Output that declares its own `success` field was misread as an
    ActionNode envelope, .get("result") returned None, and the LLM saw
    {"result": null} for every task_manager call."""
    from nodes.tool.task_manager import TaskManagerNode

    flat = {"success": True, "operation": "list_tasks", "tasks": [], "count": 0}

    async def fake_execute(args, config):
        return flat

    node = TaskManagerNode()
    with patch("nodes.tool.task_manager._execute_task_manager", fake_execute):
        result = await node.execute_as_tool(
            {"operation": "list_tasks", "include_history": True},
            {},
            NodeContext(node_id="wf:taskManager:1", node_type="taskManager", raw={}),
        )

    assert result == flat
    assert result["tasks"] == []  # the lead can actually see the list


@pytest.mark.asyncio
async def test_operation_error_surfaces_as_error_dict_to_the_llm():
    """Plain exceptions from the operation must reach the LLM as
    {"error": ...} — never as a silently-empty result."""
    from nodes.tool.task_manager import TaskManagerNode

    async def fake_execute(args, config):
        raise ValueError("No team exists for this lead execution")

    node = TaskManagerNode()
    with patch("nodes.tool.task_manager._execute_task_manager", fake_execute):
        result = await node.execute_as_tool(
            {"operation": "list_tasks"},
            {},
            NodeContext(node_id="wf:taskManager:1", node_type="taskManager", raw={}),
        )

    assert result == {"error": "No team exists for this lead execution"}
