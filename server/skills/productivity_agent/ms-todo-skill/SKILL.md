---
name: ms-todo-skill
description: Create, list, update, complete, and delete Microsoft To Do tasks and lists via Microsoft Graph. Supports due dates, priorities, and statuses.
allowed-tools: "ms_todo"
metadata:
  author: opencompany
  version: "1.0"
  category: productivity

---

# Microsoft To Do Skill

Manage Microsoft To Do — create, list, update, complete, and delete tasks and lists — using the Microsoft Graph API (To Do / Microsoft 365).

## Tool: ms_todo

Consolidated Microsoft To Do tool with an `operation` parameter.

### Operations

| Operation | Description | Required Fields |
|-----------|-------------|-----------------|
| `list_lists` | Enumerate the user's task lists | (none) |
| `create_list` | Create a new task list | list_name |
| `delete_list` | Delete a task list | list_id |
| `create_task` | Create a task in a list | list_id, title |
| `list_tasks` | List tasks in a list | list_id |
| `update_task` | Update a task | list_id, task_id |
| `complete_task` | Mark a task completed | list_id, task_id |
| `delete_task` | Delete a task | list_id, task_id |

Task operations require `list_id` — call `list_lists` first if you don't know it.

### list_lists - Enumerate task lists

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"list_lists"` |

**Example:**
```json
{
  "operation": "list_lists"
}
```

### create_list - Create a task list

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"create_list"` |
| list_name | string | Yes | New list display name |

**Example:**
```json
{
  "operation": "create_list",
  "list_name": "Proyectos Q3"
}
```

### create_task - Create a task

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"create_task"` |
| list_id | string | Yes | Target list ID (from `list_lists`) |
| title | string | Yes | Task title |
| body | string | No | Task notes/description |
| due_date | string | No | Due date/time in ISO 8601 |
| timezone | string | No | IANA/Windows time zone (default: UTC) |
| importance | string | No | `low` / `normal` / `high` (default: normal) |

**Example:**
```json
{
  "operation": "create_task",
  "list_id": "AAMkAGI2...",
  "title": "Revisar propuesta",
  "body": "Comentarios del cliente",
  "due_date": "2026-11-05T17:00:00",
  "importance": "high"
}
```

### list_tasks - List tasks in a list

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"list_tasks"` |
| list_id | string | Yes | Target list ID |
| show_completed | boolean | No | Include completed tasks (default: false) |
| max_results | integer | No | Maximum results (default: 25, max: 100) |

**Example:**
```json
{
  "operation": "list_tasks",
  "list_id": "AAMkAGI2..."
}
```

### update_task - Update a task

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"update_task"` |
| list_id | string | Yes | Target list ID |
| task_id | string | Yes | Task ID (from `create_task` / `list_tasks`) |
| update_title | string | No | New title |
| update_body | string | No | New notes |
| update_due_date | string | No | New due date/time (ISO 8601) |
| update_status | string | No | `notStarted` / `inProgress` / `completed` / `waitingOnOthers` / `deferred` |

At least one `update_*` field must be provided.

**Example:**
```json
{
  "operation": "update_task",
  "list_id": "AAMkAGI2...",
  "task_id": "AAAA...",
  "update_due_date": "2026-11-10T09:00:00",
  "update_status": "inProgress"
}
```

### complete_task - Mark a task completed

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"complete_task"` |
| list_id | string | Yes | Target list ID |
| task_id | string | Yes | Task ID |

**Example:**
```json
{
  "operation": "complete_task",
  "list_id": "AAMkAGI2...",
  "task_id": "AAAA..."
}
```

### delete_task - Delete a task

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| operation | string | Yes | Must be `"delete_task"` |
| list_id | string | Yes | Target list ID |
| task_id | string | Yes | Task ID |

**Example:**
```json
{
  "operation": "delete_task",
  "list_id": "AAMkAGI2...",
  "task_id": "AAAA..."
}
```

## Common Workflows

1. **Daily planning**: `list_lists` → `list_tasks` for the relevant list; surface open tasks.
2. **Capture a task**: `create_task` with title + due date; use `importance: "high"` for urgent items.
3. **Weekly review**: `list_tasks` with `show_completed: true` to see what was done.
4. **Finish a task**: `complete_task` (or `update_task` with `update_status` to set `inProgress` while working).
5. **New project**: `create_list` for the project, then `create_task` for each deliverable.

## Setup Requirements

1. Connect the Microsoft To Do node to an AI Agent's `input-tools` handle.
2. Authenticate with Microsoft in the Credentials Modal (Work/School account).
3. Ensure the Tasks.ReadWrite scope is granted.
