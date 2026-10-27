"""Contract for the workflowIntrospect tool.

The tool reads OTHER namespaces' ``workflow.db`` files — the one place
where the tenancy boundary is crossed on purpose — so the tests pin the
guardrails that make that safe: shape-validated namespace names (no path
traversal), read-only connections, never-touch-credentials, the optional
``AUDITABLE_NAMESPACES`` allowlist, and payload truncation that keeps a
53-node definition inside a broadcastable size.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from nodes.workflow.workflow_introspect import (
    ALLOWLIST_ENV,
    WorkflowIntrospectNode,
    WorkflowIntrospectParams,
    _connect_readonly,
    _truncate_deep,
)
from services.plugin import NodeContext, NodeUserError

WF_ID = "wf1234567890abcdef1234567890abcd"


def _make_ns_db(root: Path, ns: str, workflows: list[dict]) -> Path:
    """Create ``namespaces/<ns>/workflow.db`` with a minimal schema."""
    ns_dir = root / "namespaces" / ns
    ns_dir.mkdir(parents=True)
    db_path = ns_dir / "workflow.db"
    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE workflows ("
        "id VARCHAR PRIMARY KEY, name VARCHAR, slug VARCHAR, "
        "description VARCHAR, data TEXT, created_at VARCHAR, updated_at VARCHAR)"
    )
    con.execute(
        "CREATE TABLE node_parameters ("
        "id VARCHAR PRIMARY KEY, node_id VARCHAR, parameters TEXT, "
        "created_at VARCHAR, updated_at VARCHAR)"
    )
    for wf in workflows:
        con.execute(
            "INSERT INTO workflows (id, name, slug, description, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                wf["id"],
                wf["name"],
                wf["slug"],
                wf.get("description", ""),
                json.dumps(wf.get("data", {})),
                "2026-10-20 00:00:00",
                "2026-10-20 00:00:00",
            ),
        )
        for node_id, params in wf.get("params", {}).items():
            con.execute(
                "INSERT INTO node_parameters (id, node_id, parameters, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (node_id, node_id, json.dumps(params), "2026-10-20 00:00:00", "2026-10-20 00:00:00"),
            )
    con.commit()
    con.close()
    return db_path


def _sample_workflow() -> dict:
    graph = {
        "nodes": [
            {"id": f"{WF_ID}:aiAgent:1", "type": "aiAgent", "data": {"label": "A1"}},
            {"id": f"{WF_ID}:masterSkill:1", "type": "masterSkill", "data": {"label": "Skills"}},
        ],
        "edges": [
            {
                "source": f"{WF_ID}:masterSkill:1",
                "target": f"{WF_ID}:aiAgent:1",
                "sourceHandle": "output-tool",
                "targetHandle": "input-tools",
            }
        ],
    }
    return {
        "id": WF_ID,
        "name": "Set Auditor",
        "slug": "Set_Auditor_1",
        "description": "audit set",
        "data": graph,
        "params": {
            f"{WF_ID}:aiAgent:1": {
                "provider": "openrouter",
                "model": "deepseek/deepseek-chat",
                "system_message": "Eres A1.",
            },
            f"{WF_ID}:masterSkill:1": {"skills_config": {"skill": {"enabled": True}}},
        },
    }


@pytest.fixture()
def host(tmp_path, monkeypatch):
    """A fake host: two namespaces + one dotted backup dir that must stay invisible."""
    root = tmp_path
    _make_ns_db(root, "alpha", [_sample_workflow()])
    _make_ns_db(root, "beta", [{"id": "x1", "name": "Otro", "slug": "Otro_1"}])
    backup = root / "namespaces" / ".owner-backup-20261020"
    backup.mkdir()
    (backup / "workflow.db").touch()
    monkeypatch.setattr(
        "nodes.workflow.workflow_introspect._namespaces_root", lambda: root / "namespaces"
    )
    monkeypatch.delenv(ALLOWLIST_ENV, raising=False)
    return root


def _ctx() -> NodeContext:
    return NodeContext(
        node_id="t:workflowIntrospect:1", node_type="workflowIntrospect", workflow_id="w1"
    )


# ---------------------------------------------------------------------------
# list_namespaces
# ---------------------------------------------------------------------------


async def test_list_namespaces_skips_dotted_backups_and_dbless_dirs(host) -> None:
    out = await WorkflowIntrospectNode().list_namespaces(
        _ctx(), WorkflowIntrospectParams()
    )
    assert out.namespaces == ["alpha", "beta"]
    assert out.count == 2


async def test_env_allowlist_restricts_visibility(host, monkeypatch) -> None:
    monkeypatch.setenv(ALLOWLIST_ENV, "beta")
    out = await WorkflowIntrospectNode().list_namespaces(
        _ctx(), WorkflowIntrospectParams()
    )
    assert out.namespaces == ["beta"]


# ---------------------------------------------------------------------------
# Namespace validation — the path-traversal boundary
# ---------------------------------------------------------------------------


async def test_traversal_namespace_is_rejected(host) -> None:
    with pytest.raises(NodeUserError, match="Invalid namespace"):
        await WorkflowIntrospectNode().list_workflows(
            _ctx(), WorkflowIntrospectParams(operation="list_workflows", namespace="../../etc")
        )


async def test_uppercase_namespace_is_rejected(host) -> None:
    with pytest.raises(NodeUserError, match="Invalid namespace"):
        await WorkflowIntrospectNode().list_workflows(
            _ctx(), WorkflowIntrospectParams(operation="list_workflows", namespace="Alpha")
        )


async def test_unknown_namespace_error_lists_available(host) -> None:
    with pytest.raises(NodeUserError, match="alpha"):
        await WorkflowIntrospectNode().list_workflows(
            _ctx(), WorkflowIntrospectParams(operation="list_workflows", namespace="gamma")
        )


# ---------------------------------------------------------------------------
# list_workflows / get_workflow
# ---------------------------------------------------------------------------


async def test_list_workflows_reads_only_target_namespace(host) -> None:
    out = await WorkflowIntrospectNode().list_workflows(
        _ctx(), WorkflowIntrospectParams(operation="list_workflows", namespace="alpha")
    )
    assert out.namespace == "alpha"
    assert [w["name"] for w in out.workflows] == ["Set Auditor"]


async def test_get_workflow_resolves_by_name_case_insensitive(host) -> None:
    out = await WorkflowIntrospectNode().get_workflow(
        _ctx(),
        WorkflowIntrospectParams(
            operation="get_workflow", namespace="alpha", workflow="set auditor"
        ),
    )
    assert out.workflow["id"] == WF_ID
    assert out.workflow["node_count"] == 2
    assert [n["type"] for n in out.nodes] == ["aiAgent", "masterSkill"]
    edge = out.edges[0]
    assert edge["sourceHandle"] == "output-tool"
    assert edge["targetHandle"] == "input-tools"
    # Parameters keyed by the SHORT node id (workflow-id prefix stripped).
    assert "aiAgent:1" in out.parameters
    assert out.parameters["aiAgent:1"]["model"] == "deepseek/deepseek-chat"


async def test_get_workflow_include_filters(host) -> None:
    node = WorkflowIntrospectNode()
    base = {"operation": "get_workflow", "namespace": "alpha", "workflow": "Set Auditor"}
    graph_only = await node.get_workflow(_ctx(), WorkflowIntrospectParams(include="graph", **base))
    params_only = await node.get_workflow(_ctx(), WorkflowIntrospectParams(include="params", **base))
    assert graph_only.parameters is None and graph_only.nodes
    assert params_only.nodes is None and params_only.edges is None and params_only.parameters


async def test_get_workflow_resolves_by_substring_when_unambiguous(host) -> None:
    # LLM ergonomics: the model says "Set", the workflow is "Set Auditor".
    out = await WorkflowIntrospectNode().get_workflow(
        _ctx(),
        WorkflowIntrospectParams(operation="get_workflow", namespace="alpha", workflow="auditor"),
    )
    assert out.workflow["id"] == WF_ID


async def test_get_workflow_ambiguous_substring_names_candidates(host) -> None:
    _make_ns_db(
        host, "amb", [
            {"id": "a1", "name": "Set Auditor Dos", "slug": "Set_Auditor_Dos_1"},
            {"id": "a2", "name": "Set Auditor Tres", "slug": "Set_Auditor_Tres_1"},
        ]
    )
    with pytest.raises(NodeUserError, match="ambiguous"):
        await WorkflowIntrospectNode().get_workflow(
            _ctx(),
            WorkflowIntrospectParams(
                operation="get_workflow", namespace="amb", workflow="set auditor"
            ),
        )


async def test_get_workflow_unknown_name_lists_candidates(host) -> None:
    with pytest.raises(NodeUserError, match="Set Auditor"):
        await WorkflowIntrospectNode().get_workflow(
            _ctx(),
            WorkflowIntrospectParams(
                operation="get_workflow", namespace="alpha", workflow="nope"
            ),
        )


async def test_long_strings_are_truncated_with_marker(host) -> None:
    long_prompt = "x" * 25_000
    _make_ns_db(
        host, "big", [{
            "id": "bigwf1", "name": "Big", "slug": "Big_1",
            "params": {"bigwf1:aiAgent:1": {"system_message": long_prompt}},
        }],
    )
    out = await WorkflowIntrospectNode().get_workflow(
        _ctx(),
        WorkflowIntrospectParams(operation="get_workflow", namespace="big", workflow="Big"),
    )
    stored = out.parameters["aiAgent:1"]["system_message"]
    assert len(stored) < len(long_prompt)
    assert "truncated" in stored
    assert any("system_message" in t for t in out.truncated)


# ---------------------------------------------------------------------------
# export_workflow — the workspace hand-off
# ---------------------------------------------------------------------------


async def test_export_writes_full_definition_and_indexes_artifacts(tmp_path, monkeypatch) -> None:
    _make_ns_db(tmp_path, "alpha", [_sample_workflow()])
    monkeypatch.setattr(
        "nodes.workflow.workflow_introspect._namespaces_root", lambda: tmp_path / "namespaces"
    )
    ctx = NodeContext(
        node_id="t:workflowIntrospect:1",
        node_type="workflowIntrospect",
        workflow_id="w1",
        workspace_dir=str(tmp_path / "ws"),
    )
    out = await WorkflowIntrospectNode().export_workflow(
        ctx,
        WorkflowIntrospectParams(operation="export_workflow", namespace="alpha", workflow="Set Auditor"),
    )
    # Default path: estructura/<ns>__<slug>.json — relative to the workspace.
    assert out.file_path == "estructura/alpha__Set_Auditor_1.json"
    written = tmp_path / "ws" / "estructura" / "alpha__Set_Auditor_1.json"
    assert written.is_file()
    on_disk = json.loads(written.read_text(encoding="utf-8"))
    assert on_disk["workflow"]["node_count"] == 2
    assert len(on_disk["edges"]) == 1
    assert on_disk["parameters"]["aiAgent:1"]["system_message"] == "Eres A1."
    # The artifact index points at the prose artifacts with exact JSON paths.
    assert ("aiAgent:1", "system_message") in {
        (a["node"], a["field"]) for a in out.artifacts
    }
    assert out.artifact_count == 1
    assert all("parameters[" in a["json_path"] for a in out.artifacts)
    # Pretty-printed for line pagination: more than one line.
    assert out.line_count > 1


async def test_export_rejects_escaping_file_path(tmp_path, monkeypatch) -> None:
    _make_ns_db(tmp_path, "alpha", [_sample_workflow()])
    monkeypatch.setattr(
        "nodes.workflow.workflow_introspect._namespaces_root", lambda: tmp_path / "namespaces"
    )
    ctx = NodeContext(
        node_id="t:workflowIntrospect:1",
        node_type="workflowIntrospect",
        workflow_id="w1",
        workspace_dir=str(tmp_path / "ws"),
    )
    with pytest.raises(NodeUserError):
        await WorkflowIntrospectNode().export_workflow(
            ctx,
            WorkflowIntrospectParams(
                operation="export_workflow", namespace="alpha", workflow="Set Auditor",
                file_path="../../outside.json",
            ),
        )
    assert not (tmp_path / "outside.json").exists()


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------


def test_connection_is_read_only(host) -> None:
    db_path = host / "namespaces" / "alpha" / "workflow.db"
    con = _connect_readonly(db_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO workflows (id) VALUES ('nope')")
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Truncation helper
# ---------------------------------------------------------------------------


def test_truncate_deep_walks_nested_structures() -> None:
    touched: list[str] = []
    value = {"a": {"b": ["short", "y" * 30]}, "c": "fine"}
    out = _truncate_deep(value, 10, touched, "")
    assert out["c"] == "fine"
    assert out["a"]["b"][0] == "short"
    assert out["a"]["b"][1].startswith("yyy")
    assert out["a"]["b"][1].endswith("]")
    assert touched == ["a.b[1]"]
