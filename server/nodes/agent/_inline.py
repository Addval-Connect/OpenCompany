"""Shared pre-dispatch logic for every agent plugin.

Every agent (ai_agent, chat_agent, the 13 SpecializedAgentBase plugins: 11 specialized plus the 2 team leads)
shares the same 3-step preamble before calling its specific AIService
method:

1. :func:`services.plugin.edge_walker.collect_agent_connections` —
   gather memory / skills / tools / input / task data.
2. Task-context injection when a taskTrigger firing carries a
   completed / errored task. Tools are deliberately KEPT: the injected
   guidance tells a team lead to ``list_tasks`` / ``accept_task`` /
   ``reassign_task``, which requires the Task Manager tool. An earlier
   version stripped every tool here "so the agent reports instead of
   re-delegating" — that made the lead unable to accept or reassign
   anything, which read as the lead forgetting its plan. The firing
   runs in a fresh execution, so the tool-facing context is re-scoped
   to the OWNING execution id carried by the task payload (the Temporal
   runtime's ``team_execution_id`` equivalent).
3. Auto-prompt fallback when the ``prompt`` field is empty and a
   connected upstream node produced output.

For team-lead agents (``orchestrator_agent`` / ``ai_employee``),
teammate agents connected via ``input-teammates`` become delegation
tools (appended to ``tool_data``), and the durable execution team is
persisted up front (mirroring the Temporal runtime's
``prepare_agent_payload``) so the lead's first ``task_manager`` call
resolves its scope; completion-review firings are excluded — they
re-scope instead of minting a second empty team.

:func:`prepare_agent_call` returns the fully-prepared kwargs to pass
to ``ai_service.execute_agent(...)`` or ``ai_service.execute_chat_agent(...)``.
"""

from __future__ import annotations

from typing import Any, Dict

from core.logging import get_logger
from services.plugin.edge_walker import (
    collect_agent_connections,
    collect_teammate_connections,
    format_task_context,
)

logger = get_logger(__name__)

# Team-lead agent types where teammates become delegation tools.
TEAM_LEAD_TYPES = frozenset({"orchestrator_agent", "ai_employee"})


async def prepare_agent_call(
    *,
    node_id: str,
    node_type: str,
    parameters: Dict[str, Any],
    context: Dict[str, Any],
    database: Any,
    log_prefix: str = "[Agent]",
) -> Dict[str, Any]:
    """Run the 3-step pre-dispatch flow and return a kwargs dict ready
    to splat into ``AIService.execute_agent`` or ``execute_chat_agent``.
    """
    # api_key is NOT a declared Params field on aiAgent/chatAgent/
    # specialized agents — credentials live in the credentials DB and
    # node_executor._inject_api_keys puts the resolved key into the
    # *raw* parameters dict before Pydantic validation strips it. Recover
    # it from context so ai_service.execute_[chat_]agent receives the
    # key it reads via ``flattened.get('api_key')``.
    raw_params = context.get("_raw_parameters") or {}
    if "api_key" in raw_params and "api_key" not in parameters:
        parameters = {**parameters, "api_key": raw_params["api_key"]}

    memory_data, skill_data, tool_data, input_data, task_data = await collect_agent_connections(
        node_id,
        context,
        database,
        log_prefix=log_prefix,
    )

    # Step 1: task-context injection. Tools are kept — the injected
    # guidance requires the Task Manager tool to act on the completion.
    if task_data:
        task_context = format_task_context(task_data)
        original_prompt = parameters.get("prompt", "")
        parameters = {**parameters, "prompt": f"{task_context}\n\n{original_prompt}"}
        logger.info(
            f"{log_prefix} Task context injected for task_id={task_data.get('task_id')}",
        )

        # A taskTrigger completion review runs in a FRESH execution, but
        # the durable team it reviews belongs to the execution that
        # assigned the work. Re-scope the run context to the owning
        # execution (the Temporal runtime does the same via
        # ``team_execution_id``) so task_manager resolves that team
        # instead of raising "No team exists for this lead execution".
        owning_execution_id = str(task_data.get("execution_id") or "")
        if owning_execution_id:
            context = {**context, "execution_id": owning_execution_id}

    # Step 2: auto-prompt fallback.
    if not parameters.get("prompt") and input_data:
        prompt = (
            (input_data.get("message") if isinstance(input_data, dict) else None)
            or (input_data.get("text") if isinstance(input_data, dict) else None)
            or (input_data.get("content") if isinstance(input_data, dict) else None)
            or str(input_data)
        )
        parameters = {**parameters, "prompt": prompt}
        shown = prompt[:100] if isinstance(prompt, str) and len(prompt) > 100 else prompt
        logger.info(f"{log_prefix} Auto-using input as prompt: {shown}...")

    # Step 3: team-lead delegation-tool injection.
    if node_type in TEAM_LEAD_TYPES:
        teammates = await collect_teammate_connections(node_id, context, database)
        if teammates:
            tool_data = tool_data or []
            for tm in teammates:
                tool_data.append(
                    {
                        "node_id": tm["node_id"],
                        "node_type": tm["node_type"],
                        "label": tm["label"],
                        "parameters": tm.get("parameters", {}),
                        "child_tools": tm.get("child_tools", []),
                        "child_skills": tm.get("child_skills", []),
                        "capabilities": tm.get("capabilities", ""),
                        "delegate_tool_name": tm["delegate_tool_name"],
                    }
                )
            logger.info(f"[Teams] Added {len(teammates)} teammates as delegation tools")

            # Persist the execution team up front, mirroring the Temporal
            # runtime (agent_activities.prepare_agent_payload). The lead's
            # system prompt forbids direct delegate_to_* calls once a Task
            # Manager is bound, so the lazy creation inside
            # _execute_delegated_agent never fires in this runtime — the
            # first task_manager assign_task then failed with "No team
            # exists for this lead execution".
            # A taskTrigger completion review (task_data present) runs in a
            # separate execution and must NOT mint a second empty team for
            # the same lead; it re-scopes to the owning execution above.
            workflow_id = str(context.get("workflow_id") or "")
            execution_id = str(context.get("execution_id") or "")
            if workflow_id and execution_id and not task_data:
                from services.agent_team import get_agent_team_service

                lead_node = next(
                    (n for n in (context.get("nodes") or []) if n.get("id") == node_id),
                    {},
                )
                team = await get_agent_team_service().get_or_create_execution_team(
                    team_lead_node_id=node_id,
                    teammates=teammates,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    root_execution_id=str(context.get("root_execution_id") or execution_id),
                    team_lead_type=node_type,
                    team_lead_label=(lead_node.get("data") or {}).get("label") or node_type,
                    config={"mode": "parallel"},
                )
                if not team:
                    raise RuntimeError("Failed to persist agent execution team")

    from services.status_broadcaster import get_status_broadcaster

    return {
        "parameters": parameters,
        "memory_data": memory_data,
        "skill_data": skill_data if skill_data else None,
        "tool_data": tool_data if tool_data else None,
        "broadcaster": get_status_broadcaster(),
        "workflow_id": context.get("workflow_id"),
        "context": context,
        "database": database,
    }
