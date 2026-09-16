"""The conversation-scope keys MachinaWorkflow stamps on a deployed run must
reach ``NodeContext.raw`` on both node-execution paths.

Without ``generation`` the Context descriptor builder returns ``None`` and
the edge walker drops the ``input-context`` edge, so every node that runs
as a per-type activity (claude_code_agent, rlm_agent) silently ran without
its Context node: no stored conversation, a fresh provider session per
message."""

from __future__ import annotations

import inspect

import pytest

SCOPE_KEYS = (
    "generation",
    "graphVersion",
    "context_execution_id",
    "context_session_id",
    "data_scope_id",
)


def test_as_activity_forwards_conversation_scope_into_context():
    from services.plugin.base import BaseNode

    source = inspect.getsource(BaseNode.as_activity.__func__)
    for key in SCOPE_KEYS:
        assert f'"{key}"' in source, (
            f"as_activity must forward {key!r} through extras; without it the "
            "Context descriptor builder sees generation 0 and drops the edge"
        )


@pytest.mark.asyncio
async def test_execute_node_adapter_forwards_conversation_scope():
    from services.workflow import WorkflowService

    captured: dict = {}

    async def fake_execute_node(self, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return {"success": True}

    svc = object.__new__(WorkflowService)
    svc.execute_node = fake_execute_node.__get__(svc, WorkflowService)

    context = {
        "nodes": [],
        "edges": [],
        "session_id": "s",
        "execution_id": "e",
        "workflow_id": "wf",
        "generation": 3,
        "graphVersion": 2,
        "context_execution_id": "wf-run-1",
        "context_session_id": "chat-1",
        "user_id": "owner",
    }
    await WorkflowService._execute_node_adapter(svc, "n1", "claude_code_agent", {}, context)

    extras = captured.get("extras") or {}
    assert extras["generation"] == 3
    assert extras["graphVersion"] == 2
    assert extras["context_execution_id"] == "wf-run-1"
    assert extras["context_session_id"] == "chat-1"
