#!/usr/bin/env python3
"""Interactive TUI for managing OpenCompany users and namespaces.

Run from the repo root (recommended):
    python server/scripts/tui.py

Or from server/:
    python scripts/tui.py

DATA_DIR is resolved via core.paths.project_root() so always pass an
absolute path or the canonical relative form (.opencompany) — never
../.opencompany, which resolves one level above the repo root.

Dev mode example (repo-local DB):
    DATA_DIR=.opencompany python server/scripts/tui.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow running from server/ or repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# If DATA_DIR is not set, default to the dev DB so the TUI targets the
# same database as `python -m cli dev` without requiring the caller to
# remember the flag.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if "DATA_DIR" not in os.environ and (_REPO_ROOT / ".opencompany").exists():
    os.environ["DATA_DIR"] = str(_REPO_ROOT / ".opencompany")

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich import box

console = Console()


# ── helpers ──────────────────────────────────────────────────────────────────

def _header(title: str) -> None:
    console.print(Panel(f"[bold cyan]{title}[/]", box=box.ROUNDED, expand=False))


def _menu(options: list[tuple[str, str]]) -> str:
    """Render numbered options and return the chosen key."""
    console.print()
    for i, (key, label) in enumerate(options, 1):
        console.print(f"  [bold cyan]{i}[/]  {label}")
    console.print()
    while True:
        raw = Prompt.ask("[bold]Choice[/]", console=console).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        if raw in {k for k, _ in options}:
            return raw
        console.print("[red]Invalid choice[/]")


def _table(title: str, columns: list[str], rows: list[list[str]]) -> None:
    t = Table(title=title, box=box.SIMPLE_HEAVY, show_header=True)
    for col in columns:
        t.add_column(col, style="dim")
    for row in rows:
        t.add_row(*row)
    console.print(t)


# ── async core ───────────────────────────────────────────────────────────────

async def _get_services():
    from core.config import Settings
    from core.database import Database
    from services.user_auth import UserAuthService
    from core.container import container

    settings = Settings()
    database = container.database()
    # Ensure owner DB is started
    from core.db_pool import DatabasePool
    pool = container._database_pool()
    await pool.startup_namespace("owner")

    auth = UserAuthService(
        database=database,
        settings=settings,
        encryption=container.encryption_service(),
        credentials_db=container.credentials_database(),
    )
    return auth, database, settings


async def list_users(auth, database, settings) -> None:
    users = await auth.list_users()
    if not users:
        console.print("[yellow]No users found.[/]")
        return
    rows = [[str(u.id), u.email, u.display_name or "", "yes" if u.is_active else "no"] for u in users]
    _table("Users", ["ID", "Email", "Name", "Active"], rows)


async def list_namespaces(auth, database, settings) -> None:
    from sqlalchemy import text
    from core.db_pool import DatabasePool
    pool = container_pool()
    owner_db = pool.get("owner")
    async with owner_db.get_session() as session:
        result = await session.execute(text(
            "SELECT namespace, display_name, status, temporal_provisioned FROM namespaces ORDER BY namespace"
        ))
        rows_raw = result.fetchall()
    if not rows_raw:
        console.print("[yellow]No namespaces found.[/]")
        return
    rows = [[r[0], r[1] or "", r[2], "yes" if r[3] else "no"] for r in rows_raw]
    _table("Namespaces", ["Slug", "Display Name", "Status", "Temporal"], rows)


def container_pool():
    from core.container import container
    return container._database_pool()


async def add_user(auth, database, settings) -> None:
    console.print()
    email = Prompt.ask("Email", console=console).strip().lower()
    name = Prompt.ask("Display name", console=console).strip()
    password = Prompt.ask("Password", console=console, password=True)

    from models.auth import User
    existing = await auth.get_user_by_email(email)
    if existing:
        console.print(f"[red]User {email} already exists.[/]")
        return

    user = User(email=email, display_name=name)
    user.set_password(password)
    from sqlalchemy import text
    pool = container_pool()
    owner_db = pool.get("owner")
    async with owner_db.get_session() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)

    console.print(f"[green]✓ Created user {email} (id={user.id})[/]")


async def change_password(auth, database, settings) -> None:
    console.print()
    email = Prompt.ask("Email", console=console).strip().lower()
    user = await auth.get_user_by_email(email)
    if not user:
        console.print(f"[red]User {email} not found.[/]")
        return
    password = Prompt.ask("New password", console=console, password=True)
    user.set_password(password)
    pool = container_pool()
    owner_db = pool.get("owner")
    async with owner_db.get_session() as session:
        from sqlalchemy import text
        await session.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :id"),
            {"h": user.password_hash, "id": user.id},
        )
        await session.commit()
    console.print(f"[green]✓ Password updated for {email}[/]")


async def create_namespace(auth, database, settings) -> None:
    console.print()
    slug = Prompt.ask("Namespace slug (lowercase, e.g. addval)", console=console).strip().lower()
    display = Prompt.ask("Display name", console=console).strip()

    # Validate slug
    import re
    if not re.match(r'^[a-z][a-z0-9-]{1,61}[a-z0-9]$', slug):
        console.print("[red]Invalid slug. Use lowercase letters, numbers, hyphens (3-63 chars).[/]")
        return

    pool = container_pool()
    owner_db = pool.get("owner")
    from sqlalchemy import text

    # Check if exists
    async with owner_db.get_session() as session:
        result = await session.execute(text("SELECT 1 FROM namespaces WHERE namespace=:ns"), {"ns": slug})
        if result.first():
            console.print(f"[yellow]Namespace '{slug}' already exists.[/]")
            return

    # Register in Temporal
    console.print(f"Registering [bold]{slug}[/] in Temporal...")
    try:
        from services.temporal.search_attributes import register_search_attributes
        from temporalio.client import Client
        from google.protobuf.duration_pb2 import Duration
        from temporalio.api.workflowservice.v1 import RegisterNamespaceRequest
        from temporalio.service import RPCError, RPCStatusCode

        client = await Client.connect(settings.temporal_server_address, namespace=settings.temporal_namespace)
        ws = client.service_client.workflow_service
        try:
            await ws.register_namespace(RegisterNamespaceRequest(
                namespace=slug,
                description=f"OpenCompany tenant: {display}",
                workflow_execution_retention_period=Duration(seconds=7 * 86400),
            ))
            console.print(f"  [green]✓ Temporal namespace registered[/]")
        except RPCError as exc:
            if exc.status != RPCStatusCode.ALREADY_EXISTS:
                raise
            console.print(f"  [yellow]Temporal namespace already exists, reusing[/]")

        await register_search_attributes(client, slug)
        console.print(f"  [green]✓ Search attributes registered[/]")
        temporal_provisioned = True
    except Exception as exc:
        console.print(f"  [yellow]Warning: Temporal registration failed: {exc}[/]")
        console.print("  Namespace will be created in DB only (temporal_provisioned=false)")
        temporal_provisioned = False

    # Save to DB
    async with owner_db.get_session() as session:
        from datetime import datetime, timezone
        await session.execute(
            text("""
                INSERT INTO namespaces (namespace, display_name, status, temporal_provisioned, created_at, updated_at)
                VALUES (:ns, :dn, 'ready', :tp, :now, :now)
            """),
            {"ns": slug, "dn": display, "tp": 1 if temporal_provisioned else 0,
             "now": datetime.now(timezone.utc)},
        )
        await session.commit()

    console.print(f"[green]✓ Namespace '{slug}' ({display}) created[/]")


async def assign_namespace(auth, database, settings) -> None:
    console.print()
    email = Prompt.ask("Email", console=console).strip().lower()
    user = await auth.get_user_by_email(email)
    if not user:
        console.print(f"[red]User {email} not found.[/]")
        return

    slug = Prompt.ask("Namespace slug", console=console).strip().lower()
    role = Prompt.ask("Role [owner/member]", default="member", console=console).strip().lower()
    if role not in ("owner", "member"):
        role = "member"

    pool = container_pool()
    owner_db = pool.get("owner")
    from sqlalchemy import text
    from datetime import datetime, timezone

    async with owner_db.get_session() as session:
        result = await session.execute(text("SELECT 1 FROM namespaces WHERE namespace=:ns"), {"ns": slug})
        if not result.first():
            console.print(f"[red]Namespace '{slug}' not found. Create it first.[/]")
            return
        await session.execute(
            text("""
                INSERT OR IGNORE INTO user_namespaces (user_id, namespace, role, assigned_at)
                VALUES (:uid, :ns, :role, :now)
            """),
            {"uid": str(user.id), "ns": slug, "role": role, "now": datetime.now(timezone.utc)},
        )
        await session.commit()

    console.print(f"[green]✓ {email} assigned to '{slug}' as {role}[/]")


async def list_user_namespaces(auth, database, settings) -> None:
    console.print()
    email = Prompt.ask("Email (leave blank for all)", default="", console=console).strip().lower()
    pool = container_pool()
    owner_db = pool.get("owner")
    from sqlalchemy import text

    async with owner_db.get_session() as session:
        if email:
            user = await auth.get_user_by_email(email)
            if not user:
                console.print(f"[red]User {email} not found.[/]")
                return
            result = await session.execute(
                text("SELECT u.email, un.namespace, un.role FROM user_namespaces un JOIN users u ON u.id=un.user_id WHERE u.email=:e ORDER BY un.namespace"),
                {"e": email},
            )
        else:
            result = await session.execute(
                text("SELECT u.email, un.namespace, un.role FROM user_namespaces un JOIN users u ON u.id=un.user_id ORDER BY u.email, un.namespace")
            )
        rows_raw = result.fetchall()

    if not rows_raw:
        console.print("[yellow]No assignments found.[/]")
        return
    _table("User ↔ Namespace", ["Email", "Namespace", "Role"], [[r[0], r[1], r[2]] for r in rows_raw])


# ── main loop ─────────────────────────────────────────────────────────────────

MENU_MAIN = [
    ("users",      "Manage users"),
    ("namespaces", "Manage namespaces"),
    ("quit",       "Quit"),
]

MENU_USERS = [
    ("list",    "List users"),
    ("add",     "Add user"),
    ("passwd",  "Change password"),
    ("assign",  "Assign user → namespace"),
    ("unlist",  "Show user ↔ namespace assignments"),
    ("back",    "Back"),
]

MENU_NS = [
    ("list",   "List namespaces"),
    ("create", "Create namespace"),
    ("back",   "Back"),
]


async def run() -> None:
    _header("OpenCompany — User & Namespace Manager")

    auth, database, settings = await _get_services()

    while True:
        console.rule()
        action = _menu(MENU_MAIN)
        if action == "quit":
            console.print("[dim]Bye.[/]")
            break

        elif action == "users":
            while True:
                console.rule("[bold]Users[/]")
                ua = _menu(MENU_USERS)
                if ua == "back":
                    break
                elif ua == "list":
                    await list_users(auth, database, settings)
                elif ua == "add":
                    await add_user(auth, database, settings)
                elif ua == "passwd":
                    await change_password(auth, database, settings)
                elif ua == "assign":
                    await assign_namespace(auth, database, settings)
                elif ua == "unlist":
                    await list_user_namespaces(auth, database, settings)

        elif action == "namespaces":
            while True:
                console.rule("[bold]Namespaces[/]")
                na = _menu(MENU_NS)
                if na == "back":
                    break
                elif na == "list":
                    await list_namespaces(auth, database, settings)
                elif na == "create":
                    await create_namespace(auth, database, settings)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/]")


if __name__ == "__main__":
    main()
