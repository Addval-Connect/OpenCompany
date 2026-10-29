"""Microsoft To Do via Microsoft Graph — multi-op ActionNode + AI tool.

Operations (dispatched off ``params.operation``):
- list_lists   -> GET    /me/todo/lists
- create_list  -> POST   /me/todo/lists
- delete_list  -> DELETE /me/todo/lists/{id}
- create_task  -> POST   /me/todo/lists/{id}/tasks
- list_tasks   -> GET    /me/todo/lists/{id}/tasks
- update_task  -> PATCH  /me/todo/lists/{id}/tasks/{id}
- complete_task-> PATCH  /me/todo/lists/{id}/tasks/{id}  (status=completed)
- delete_task  -> DELETE /me/todo/lists/{id}/tasks/{id}

To Do lives under the signed-in user only (``/me/todo``) — unlike Mail and
Calendar there is no shared-mailbox routing: Graph exposes To Do per
account and shared lists are not part of the v1.0 surface. Scope:
``Tasks.ReadWrite`` (declared in ``server/config/microsoft_apis.json``).
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.plugin import ActionNode, NodeContext, NodeUserError, Operation, TaskQueue

from .._base import graph_request, track_microsoft_usage
from .._credentials import MicrosoftCredential

_LIST_LISTS = {"displayOptions": {"show": {"operation": ["list_lists"]}}}
_CREATE_LIST = {"displayOptions": {"show": {"operation": ["create_list"]}}}
_LIST_ONLY = {"displayOptions": {"show": {"operation": ["list_lists", "create_list"]}}}
_TASK_OPS = {
    "displayOptions": {
        "show": {
            "operation": ["create_task", "list_tasks", "update_task", "complete_task", "delete_task"]
        }
    }
}
_TASK_TARGET_OPS = {"displayOptions": {"show": {"operation": ["update_task", "complete_task", "delete_task"]}}}
_UPDATE_ONLY = {"displayOptions": {"show": {"operation": ["update_task"]}}}
_LIST_TASKS_ONLY = {"displayOptions": {"show": {"operation": ["list_tasks"]}}}
_CREATE_TASK_ONLY = {"displayOptions": {"show": {"operation": ["create_task"]}}}
_DELETE_LIST_ONLY = {"displayOptions": {"show": {"operation": ["delete_list"]}}}


class TodoParams(BaseModel):
    operation: Literal[
        "list_lists",
        "create_list",
        "delete_list",
        "create_task",
        "list_tasks",
        "update_task",
        "complete_task",
        "delete_task",
    ] = "list_tasks"

    # Task operations need the target list; obtain it from `list_lists`.
    list_id: str = Field(default="", json_schema_extra=_TASK_OPS)

    # create_list
    list_name: str = Field(default="", json_schema_extra=_CREATE_LIST)

    # create_task
    title: str = Field(default="", json_schema_extra=_CREATE_TASK_ONLY)
    body: str = Field(default="", json_schema_extra={"rows": 3, **_CREATE_TASK_ONLY})
    due_date: str = Field(
        default="",
        json_schema_extra={"placeholder": "2026-08-10T17:00:00", **_CREATE_TASK_ONLY},
    )
    timezone: str = Field(default="UTC", json_schema_extra=_CREATE_TASK_ONLY)
    importance: Literal["low", "normal", "high"] = Field(default="normal", json_schema_extra=_CREATE_TASK_ONLY)

    # list_tasks
    show_completed: bool = Field(default=False, json_schema_extra=_LIST_TASKS_ONLY)
    max_results: int = Field(default=25, ge=1, le=100, json_schema_extra=_LIST_TASKS_ONLY)

    # update_task
    task_id: str = Field(default="", json_schema_extra=_TASK_TARGET_OPS)
    update_title: str = Field(default="", json_schema_extra=_UPDATE_ONLY)
    update_body: str = Field(default="", json_schema_extra={"rows": 3, **_UPDATE_ONLY})
    update_due_date: str = Field(default="", json_schema_extra=_UPDATE_ONLY)
    update_status: Literal["", "notStarted", "inProgress", "completed", "waitingOnOthers", "deferred"] = Field(
        default="",
        json_schema_extra=_UPDATE_ONLY,
    )

    model_config = ConfigDict(extra="ignore")


class TodoOutput(BaseModel):
    operation: Optional[str] = None
    list_id: Optional[str] = None
    list_name: Optional[str] = None
    lists: Optional[List[dict]] = None
    task_id: Optional[str] = None
    title: Optional[str] = None
    due: Optional[str] = None
    importance: Optional[str] = None
    status: Optional[str] = None
    body: Optional[str] = None
    tasks: Optional[List[dict]] = None
    count: Optional[int] = None
    completed: Optional[bool] = None
    deleted: Optional[bool] = None

    model_config = ConfigDict(extra="allow")


def _task_base(list_id: str) -> str:
    return f"/me/todo/lists/{list_id}/tasks"


def _summarize_task(t: dict) -> dict:
    return {
        "task_id": t.get("id"),
        "title": t.get("title", ""),
        "status": t.get("status", ""),
        "importance": t.get("importance", ""),
        "due": ((t.get("dueDateTime") or {}).get("dateTime")),
        "created": t.get("createdDateTime"),
        "body": ((t.get("body") or {}).get("content")) or "",
    }


def _summarize_list(l: dict) -> dict:
    return {
        "list_id": l.get("id"),
        "list_name": l.get("displayName", ""),
        "is_owner": l.get("isOwner"),
    }


class TodoNode(ActionNode):
    type = "msTodo"
    display_name = "Microsoft To Do"
    subtitle = "Task Management"
    group = ("microsoft", "tool")
    description = "Microsoft To Do create / list / update / complete / delete tasks and lists via Graph (workflow + AI tool)"
    component_kind = "square"
    tool_name = "ms_todo"
    tool_description = (
        "Manage Microsoft To Do via Microsoft Graph. Operations: list_lists (enumerate task lists), "
        "create_list (new list), delete_list (remove a list), create_task (new task in a list), "
        "list_tasks (tasks in a list), update_task (modify title/body/due/status), "
        "complete_task (mark a task done), delete_task (remove a task)."
    )
    handles = (
        {"name": "input-main", "kind": "input", "position": "left", "label": "Input", "role": "main"},
        {"name": "output-main", "kind": "output", "position": "right", "label": "Output", "role": "main"},
    )
    credentials = (MicrosoftCredential,)
    annotations = {"destructive": False, "readonly": False, "open_world": True}
    task_queue = TaskQueue.REST_API
    usable_as_tool = True

    Params = TodoParams
    Output = TodoOutput

    @Operation("dispatch")
    async def dispatch(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        op = params.operation
        if op == "list_lists":
            return await self._list_lists(ctx, params)
        if op == "create_list":
            return await self._create_list(ctx, params)
        if op == "delete_list":
            return await self._delete_list(ctx, params)
        if op == "create_task":
            return await self._create_task(ctx, params)
        if op == "list_tasks":
            return await self._list_tasks(ctx, params)
        if op == "update_task":
            return await self._update_task(ctx, params)
        if op == "complete_task":
            return await self._complete_task(ctx, params)
        if op == "delete_task":
            return await self._delete_task(ctx, params)
        raise NodeUserError(f"Unknown To Do operation: {op}")

    async def _list_lists(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        data = await graph_request(ctx, "GET", "/me/todo/lists", params={"$top": 100})
        items = (data or {}).get("value", [])
        formatted = [_summarize_list(l) for l in items]
        await track_microsoft_usage(ctx.node_id, "todo_list", len(formatted), ctx.raw)
        return TodoOutput(operation="list_lists", lists=formatted, count=len(formatted))

    async def _create_list(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        if not params.list_name:
            raise NodeUserError("List name is required")
        result = await graph_request(ctx, "POST", "/me/todo/lists", json={"displayName": params.list_name})
        await track_microsoft_usage(ctx.node_id, "todo_create", 1, ctx.raw)
        summary = _summarize_list(result or {})
        return TodoOutput(
            operation="create_list",
            list_id=summary["list_id"],
            list_name=summary["list_name"],
        )

    async def _delete_list(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        if not params.list_id:
            raise NodeUserError("List ID is required")
        await graph_request(ctx, "DELETE", f"/me/todo/lists/{params.list_id}")
        await track_microsoft_usage(ctx.node_id, "todo_delete", 1, ctx.raw)
        return TodoOutput(operation="delete_list", deleted=True, list_id=params.list_id)

    async def _create_task(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        if not params.list_id:
            raise NodeUserError("List ID is required (call list_lists first)")
        if not params.title:
            raise NodeUserError("Task title is required")

        task: dict = {"title": params.title}
        if params.body:
            task["body"] = {"contentType": "Text", "content": params.body}
        if params.due_date:
            task["dueDateTime"] = {"dateTime": params.due_date, "timeZone": params.timezone}
        if params.importance != "normal":
            task["importance"] = params.importance

        result = await graph_request(ctx, "POST", _task_base(params.list_id), json=task)
        await track_microsoft_usage(ctx.node_id, "todo_create", 1, ctx.raw)
        summary = _summarize_task(result or {})
        return TodoOutput(
            operation="create_task",
            list_id=params.list_id,
            task_id=summary["task_id"],
            title=summary["title"],
            due=summary["due"],
            importance=summary["importance"],
            status=summary["status"],
        )

    async def _list_tasks(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        if not params.list_id:
            raise NodeUserError("List ID is required (call list_lists first)")

        query: dict = {"$top": min(params.max_results, 100), "$orderby": "createdDateTime desc"}
        if not params.show_completed:
            query["$filter"] = "status ne 'completed'"

        data = await graph_request(ctx, "GET", _task_base(params.list_id), params=query)
        items = (data or {}).get("value", [])
        formatted = [_summarize_task(t) for t in items]
        await track_microsoft_usage(ctx.node_id, "todo_list", len(formatted), ctx.raw)
        return TodoOutput(operation="list_tasks", list_id=params.list_id, tasks=formatted, count=len(formatted))

    async def _update_task(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        self._require_task_target(params)
        patch: dict = {}
        if params.update_title:
            patch["title"] = params.update_title
        if params.update_body:
            patch["body"] = {"contentType": "Text", "content": params.update_body}
        if params.update_due_date:
            patch["dueDateTime"] = {"dateTime": params.update_due_date, "timeZone": params.timezone}
        if params.update_status:
            patch["status"] = params.update_status

        if not patch:
            raise NodeUserError("No update fields provided")

        result = await graph_request(ctx, "PATCH", self._task_path(params), json=patch)
        await track_microsoft_usage(ctx.node_id, "todo_update", 1, ctx.raw)
        summary = _summarize_task(result or {})
        return TodoOutput(
            operation="update_task",
            list_id=params.list_id,
            task_id=summary["task_id"] or params.task_id,
            title=summary["title"],
            due=summary["due"],
            importance=summary["importance"],
            status=summary["status"],
        )

    async def _complete_task(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        self._require_task_target(params)
        result = await graph_request(ctx, "PATCH", self._task_path(params), json={"status": "completed"})
        await track_microsoft_usage(ctx.node_id, "todo_update", 1, ctx.raw)
        summary = _summarize_task(result or {})
        return TodoOutput(
            operation="complete_task",
            list_id=params.list_id,
            task_id=summary["task_id"] or params.task_id,
            title=summary["title"],
            status=summary["status"],
            completed=True,
        )

    async def _delete_task(self, ctx: NodeContext, params: TodoParams) -> TodoOutput:
        self._require_task_target(params)
        await graph_request(ctx, "DELETE", self._task_path(params))
        await track_microsoft_usage(ctx.node_id, "todo_delete", 1, ctx.raw)
        return TodoOutput(operation="delete_task", deleted=True, list_id=params.list_id, task_id=params.task_id)

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_task_target(params: TodoParams) -> None:
        if not params.list_id:
            raise NodeUserError("List ID is required (call list_lists first)")
        if not params.task_id:
            raise NodeUserError("Task ID is required")

    @staticmethod
    def _task_path(params: TodoParams) -> str:
        return f"{_task_base(params.list_id)}/{params.task_id}"
