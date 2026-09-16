"""Focused contracts for Context-backed Temporal agent orchestration.

The retired ``_thread_inputs`` session-routing tests are gone with the
journal: the plain conversation store keys on
``(workflow_id, generation, agent_node_id)`` and deliberately ignores
session identity, so every firing of an agent continues one conversation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def _settings(*, enabled: bool = True):
    return SimpleNamespace(
        temporal_agent_workflow_enabled=enabled,
        temporal_per_type_dispatch=True,
        temporal_worker_pool_enabled=False,
    )


def test_admitted_generation_routes_to_child_workflow_but_missing_metadata_stays_activity():
    from services.temporal.workflow import MachinaWorkflow

    instance = MachinaWorkflow()
    with patch("core.config.Settings", side_effect=lambda: _settings()):
        admitted = instance._resolve_dispatch(
            "aiAgent",
            graph_version=2,
            generation=4,
            context_enabled=True,
        )
        missing_generation = instance._resolve_dispatch(
            "aiAgent",
            graph_version=2,
            generation=0,
            context_enabled=True,
        )
        missing_version = instance._resolve_dispatch(
            "aiAgent",
            graph_version=0,
            generation=4,
            context_enabled=True,
        )

    assert admitted == {
        "kind": "child_workflow",
        "name": "AgentWorkflow",
    }
    assert missing_generation["name"] == "AgentWorkflow"
    assert missing_version["name"] == "AgentWorkflow"
