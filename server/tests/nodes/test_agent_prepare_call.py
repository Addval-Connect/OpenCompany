"""Contracts for the shared agent pre-dispatch flow (prepare_agent_call)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _connections(*, task_data=None, tool_data=None):
    return (
        None,  # memory_data
        None,  # skill_data
        tool_data,
        None,  # input_data
        task_data,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "error"])
async def test_completion_firing_keeps_tools(status):
    """The taskTrigger prompt tells a lead to list/accept/reassign via the
    Task Manager tool — stripping tools on exactly that firing made the
    lead unable to act on any completion (it could only answer in prose,
    which read as the lead forgetting its plan)."""
    import nodes.agent._inline as inline

    tools = [
        {"node_id": "tm-1", "node_type": "taskManager", "label": "Task Manager"},
        {"node_id": "search-1", "node_type": "braveSearch", "label": "Search"},
    ]
    task = {"task_id": "task-1", "status": status, "result": "done"}

    with patch.object(
        inline,
        "collect_agent_connections",
        AsyncMock(return_value=_connections(task_data=task, tool_data=tools)),
    ), patch.object(
        inline,
        "collect_teammate_connections",
        AsyncMock(return_value=[]),
    ), patch(
        "services.status_broadcaster.get_status_broadcaster",
        MagicMock(),
    ):
        prepared = await inline.prepare_agent_call(
            node_id="lead-1",
            node_type="orchestrator_agent",
            parameters={"prompt": "review"},
            context={},
            database=object(),
        )

    assert prepared["tool_data"] == tools
    # The task context is still injected ahead of the original prompt.
    assert "task-1" in prepared["parameters"]["prompt"]
    assert prepared["parameters"]["prompt"].endswith("review")


def _teammates():
    return [
        {
            "node_id": "tm-1",
            "node_type": "aiAgent",
            "label": "Researcher",
            "parameters": {},
            "child_tools": [],
            "child_skills": [],
            "capabilities": "",
            "delegate_tool_name": "delegate_to_researcher",
        }
    ]


def _team_service_mock():
    service = MagicMock()
    service.get_or_create_execution_team = AsyncMock(return_value={"team_id": "team_x", "id": "team_x"})
    return service


@pytest.mark.asyncio
async def test_team_lead_eagerly_creates_execution_team():
    """The legacy runtime must persist the execution team before the lead's
    first tool call: the system prompt forbids direct delegate_to_* calls,
    so the lazy creation inside _execute_delegated_agent never fires and the
    first task_manager assign_task raised "No team exists for this lead
    execution". Mirrors the Temporal runtime's prepare_agent_payload."""
    import nodes.agent._inline as inline

    service = _team_service_mock()
    context = {
        "workflow_id": "wf-1",
        "execution_id": "exec-1",
        "root_execution_id": "root-1",
        "nodes": [{"id": "lead-1", "type": "orchestrator_agent", "data": {"label": "Lead"}}],
        "edges": [],
    }

    with patch.object(
        inline,
        "collect_agent_connections",
        AsyncMock(return_value=_connections(tool_data=[{"node_id": "tmgr-1", "node_type": "taskManager"}])),
    ), patch.object(
        inline,
        "collect_teammate_connections",
        AsyncMock(return_value=_teammates()),
    ), patch(
        "services.agent_team.get_agent_team_service",
        return_value=service,
    ), patch(
        "services.status_broadcaster.get_status_broadcaster",
        MagicMock(),
    ):
        prepared = await inline.prepare_agent_call(
            node_id="lead-1",
            node_type="orchestrator_agent",
            parameters={"prompt": "go"},
            context=context,
            database=object(),
        )

    service.get_or_create_execution_team.assert_awaited_once_with(
        team_lead_node_id="lead-1",
        teammates=_teammates(),
        workflow_id="wf-1",
        execution_id="exec-1",
        root_execution_id="root-1",
        team_lead_type="orchestrator_agent",
        team_lead_label="Lead",
        config={"mode": "parallel"},
    )
    # The delegation tools were still injected alongside team creation.
    assert any(t.get("delegate_tool_name") == "delegate_to_researcher" for t in prepared["tool_data"])


@pytest.mark.asyncio
async def test_completion_firing_does_not_create_team():
    """A taskTrigger completion review runs in a separate execution — it
    must not mint a second empty team for the same lead (the owning
    execution's submitted/accepted tasks would seem to disappear)."""
    import nodes.agent._inline as inline

    service = _team_service_mock()
    task = {"task_id": "task-1", "status": "completed", "result": "done"}

    with patch.object(
        inline,
        "collect_agent_connections",
        AsyncMock(return_value=_connections(task_data=task)),
    ), patch.object(
        inline,
        "collect_teammate_connections",
        AsyncMock(return_value=_teammates()),
    ), patch(
        "services.agent_team.get_agent_team_service",
        return_value=service,
    ), patch(
        "services.status_broadcaster.get_status_broadcaster",
        MagicMock(),
    ):
        await inline.prepare_agent_call(
            node_id="lead-1",
            node_type="orchestrator_agent",
            parameters={"prompt": "review"},
            context={"workflow_id": "wf-1", "execution_id": "exec-review"},
            database=object(),
        )

    service.get_or_create_execution_team.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_firing_rescopes_execution_context():
    """The review run's tool context must resolve the OWNING execution's
    team, not the fresh review execution (Temporal does this via
    team_execution_id). The caller's context dict is left untouched."""
    import nodes.agent._inline as inline

    task = {"task_id": "task-1", "status": "completed", "result": "done", "execution_id": "exec-owning"}
    context = {"workflow_id": "wf-1", "execution_id": "exec-review"}

    with patch.object(
        inline,
        "collect_agent_connections",
        AsyncMock(return_value=_connections(task_data=task)),
    ), patch.object(
        inline,
        "collect_teammate_connections",
        AsyncMock(return_value=[]),
    ), patch(
        "services.status_broadcaster.get_status_broadcaster",
        MagicMock(),
    ):
        prepared = await inline.prepare_agent_call(
            node_id="lead-1",
            node_type="orchestrator_agent",
            parameters={"prompt": "review"},
            context=context,
            database=object(),
        )

    assert prepared["context"]["execution_id"] == "exec-owning"
    assert context["execution_id"] == "exec-review"


@pytest.mark.asyncio
async def test_team_lead_without_execution_id_skips_team_creation():
    """No execution identity means no durable scope — the team lookup would
    miss anyway, so creation is deferred rather than persisting an
    unscoped team."""
    import nodes.agent._inline as inline

    service = _team_service_mock()

    with patch.object(
        inline,
        "collect_agent_connections",
        AsyncMock(return_value=_connections()),
    ), patch.object(
        inline,
        "collect_teammate_connections",
        AsyncMock(return_value=_teammates()),
    ), patch(
        "services.agent_team.get_agent_team_service",
        return_value=service,
    ), patch(
        "services.status_broadcaster.get_status_broadcaster",
        MagicMock(),
    ):
        await inline.prepare_agent_call(
            node_id="lead-1",
            node_type="orchestrator_agent",
            parameters={"prompt": "go"},
            context={"workflow_id": "wf-1"},
            database=object(),
        )

    service.get_or_create_execution_team.assert_not_awaited()
