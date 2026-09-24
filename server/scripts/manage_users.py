"""Operator CLI for the login accounts of a deployed instance.

``AUTH_MODE=single`` closes public registration once the owner account
exists, and there is no admin API for user management. This script is the
supported way to add further logins without opening ``/register`` to the whole
internet (``AUTH_MODE=multi``).

Read this before adding anyone: the app has NO per-user data isolation.
``request.state.user_id`` is written by the auth middleware and read by
nothing, so every account shares one workflow store and one credential store.
A new login can see and edit every workflow and use every stored API key. This
adds a *login*, not a tenant. See the Known Limitations section of
``docs-internal/authentication.md``.

Run from ``server/`` so ``Settings`` finds ``../.env``:

    .venv/bin/python scripts/manage_users.py list
    .venv/bin/python scripts/manage_users.py add --email a@b.cl --name "A B"
    .venv/bin/python scripts/manage_users.py passwd --email a@b.cl
    .venv/bin/python scripts/manage_users.py rename --email a@b.cl --name "A Better Name"
    .venv/bin/python scripts/manage_users.py disable --email a@b.cl
    .venv/bin/python scripts/manage_users.py enable  --email a@b.cl
    .venv/bin/python scripts/manage_users.py remove  --email a@b.cl
    .venv/bin/python scripts/manage_users.py namespace
    .venv/bin/python scripts/manage_users.py namespace --email a@b.cl --namespace tenant-a
    .venv/bin/python scripts/manage_users.py namespace --email a@b.cl --disable

On the EC2 host (the .env is 0600 and owned by oc-app-user, so the command must
run as that user):

    cd /opt/opencompany/server
    sudo -u oc-app-user env HOME=/home/oc-app-user .venv/bin/python \
        scripts/manage_users.py list

Safe to run against a live instance: it opens the same SQLite database the
backend uses and holds a write lock only for the duration of one statement.
No restart is needed -- accounts are read per request.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path


def _bootstrap_path() -> None:
    """Make ``core`` / ``models`` / ``services`` importable from anywhere."""
    server_dir = Path(__file__).resolve().parent.parent
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))

    # Database startup logs a handful of INFO lines to stdout, which would
    # bury a generated password in noise. An env var outranks the .env value
    # in pydantic-settings, and ``setdefault`` keeps ``LOG_LEVEL=DEBUG
    # scripts/manage_users.py ...`` working for diagnosis.
    os.environ.setdefault("LOG_LEVEL", "WARNING")


def _generated_password() -> str:
    """A password the operator hands over once, out of band."""
    return secrets.token_urlsafe(16)


async def _service():
    """UserAuthService on the real, already-migrated database.

    ``encryption`` and ``credentials_db`` are ``None``: the service stores the
    references but touches neither on any path this script calls. The
    server-scoped encryption key belongs to the running backend and is
    deliberately not initialised here.
    """
    from core.config import Settings
    from core.database import Database
    from core.logging import configure_logging
    from services.user_auth import UserAuthService

    settings = Settings()
    # Without this the process runs on structlog's default config, which
    # emits `Database initialized successfully` and friends to stdout at INFO
    # -- enough to bury a generated password. ``LOG_LEVEL`` was defaulted to
    # WARNING in ``_bootstrap_path``.
    configure_logging(settings)
    database = Database(settings)
    await database.startup()
    service = UserAuthService(
        database=database,
        settings=settings,
        encryption=None,  # type: ignore[arg-type]
        credentials_db=None,  # type: ignore[arg-type]
    )
    return service, database, settings


def _print_users(users) -> None:
    if not users:
        print("No accounts. The next visitor to /register becomes the owner.")
        return
    print(f"{'id':>3}  {'email':<38} {'name':<22} {'owner':<6} {'active':<6} last login")
    print("-" * 100)
    for user in users:
        last = user.last_login.isoformat(timespec="seconds") if user.last_login else "never"
        print(
            f"{user.id:>3}  {user.email:<38} {user.display_name:<22} "
            f"{'yes' if user.is_owner else 'no':<6} {'yes' if user.is_active else 'no':<6} {last}"
        )


def _print_namespaces(rows, users, settings) -> None:
    """The account -> Temporal namespace table, with the flag state above it.

    The flag state is printed first on purpose: a populated table means
    nothing while ``MULTI_TENANT_NAMESPACES=false``, and an operator
    reading only the rows would conclude the isolation is live.
    """
    from constants import OWNER_PRINCIPAL_ID

    enabled = bool(getattr(settings, "multi_tenant_namespaces", False))
    print(
        f"MULTI_TENANT_NAMESPACES={'true' if enabled else 'false'}  "
        f"default namespace={settings.temporal_namespace}"
    )
    if not enabled:
        print("Flag is off: every account executes in the default namespace and the "
              "assignments below are not read at runtime.")
    if not rows:
        print("No namespace assignments.")
        return

    email_by_id = {str(user.id): user.email for user in users}
    print()
    print(f"{'user_id':<10} {'account':<38} {'namespace':<28} {'status':<13} assigned")
    print("-" * 110)
    for row in rows:
        user_id = row["user_id"]
        account = email_by_id.get(user_id)
        if account is None:
            account = "(owner principal)" if user_id == OWNER_PRINCIPAL_ID else "(no account row)"
        assigned = (row.get("created_at") or "")[:19]
        print(
            f"{user_id:<10} {account:<38} {row['namespace']:<28} "
            f"{row['status']:<13} {assigned}"
        )
    print()
    print("Only status=ready routes traffic; provisioning and disabled fall back to "
          f"{settings.temporal_namespace}.")


async def _provision_namespace(settings, namespace: str, owner_email: str, retention_days: int) -> bool:
    """Register ``namespace`` on the running Temporal server and wait for it.

    Registration is hot -- the dev server accepts a new namespace without a
    restart -- but the frontend's namespace registry cache is NOT immediately
    consistent, so a describe poll follows before the caller marks the row
    ready. Search attributes are registered here too, and a failure there is
    fatal to provisioning: the Visibility queries behind event dispatch and
    workflow-control reconciliation are built on them, so a namespace missing
    them would accept workflows and then never fire a trigger.

    Returns False (with an explanation on stderr) when the server is
    unreachable or never converges. The caller then leaves the row at
    ``provisioning``, which resolves to the default namespace -- the account
    keeps working while the operator fixes the server and re-runs.
    """
    from google.protobuf.duration_pb2 import Duration
    from temporalio.api.workflowservice.v1 import (
        DescribeNamespaceRequest,
        RegisterNamespaceRequest,
    )
    from temporalio.client import Client
    from temporalio.service import RPCError, RPCStatusCode

    from services.temporal.search_attributes import register_search_attributes

    if retention_days < 1:
        # Temporal rejects a retention shorter than a day outright.
        print("FAILED: --retention-days must be at least 1", file=sys.stderr)
        return False

    address = settings.temporal_server_address
    # No TracingInterceptor here, unlike TemporalClientWrapper: this is a
    # one-shot control-plane client that starts no workflows, and tracing
    # ownership is "exactly once per Client.connect" -- a CLI has nothing to
    # correlate.
    try:
        client = await Client.connect(address, namespace=settings.temporal_namespace)
    except Exception as exc:  # noqa: BLE001 -- any transport failure reads the same
        print(f"FAILED: cannot reach Temporal at {address}: {exc}", file=sys.stderr)
        return False

    workflow_service = client.service_client.workflow_service
    try:
        await workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=namespace,
                description=f"OpenCompany tenant for {owner_email}",
                owner_email=owner_email,
                # Retention reaps CLOSED executions only, so running and
                # paused deployments are untouched by it -- the months-long
                # durability contract is unaffected by a short value here.
                workflow_execution_retention_period=Duration(seconds=retention_days * 86400),
            )
        )
        print(f"Registered namespace {namespace} (retention {retention_days}d)")
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            print(f"FAILED: register_namespace({namespace}): {exc}", file=sys.stderr)
            return False
        # Re-running the command against an existing namespace is a no-op,
        # which is what makes this whole subcommand safe to repeat.
        print(f"Namespace {namespace} already exists on the server; reusing it")

    attempts = max(int(settings.temporal_health_check_attempts), 1) * 4
    delay = float(settings.temporal_health_check_delay_seconds)
    for attempt in range(1, attempts + 1):
        try:
            await workflow_service.describe_namespace(
                DescribeNamespaceRequest(namespace=namespace)
            )
            break
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                print(f"FAILED: describe_namespace({namespace}): {exc}", file=sys.stderr)
                return False
            if attempt < attempts:
                await asyncio.sleep(delay)
    else:
        print(
            f"FAILED: {namespace} was registered but the server still reports it "
            f"missing after {attempts} checks ({attempts * delay:.0f}s)",
            file=sys.stderr,
        )
        return False

    results = await register_search_attributes(client, namespace)
    failed = {name: value for name, value in results.items() if value.startswith("error")}
    if failed:
        print(f"FAILED: search attributes on {namespace}: {failed}", file=sys.stderr)
        return False
    registered = sum(1 for value in results.values() if value == "registered")
    present = sum(1 for value in results.values() if value == "already_exists")
    print(f"Search attributes on {namespace}: {registered} registered, {present} already present")
    return True


async def _run_namespace(args: argparse.Namespace, service, database, settings) -> int:
    from constants import OWNER_PRINCIPAL_ID
    from services.tenancy import (
        STATUS_DISABLED,
        STATUS_PROVISIONING,
        STATUS_READY,
        validate_namespace,
    )

    if not (args.namespace or args.disable or args.enable):
        rows = await database.list_tenant_namespaces()
        users = await service.list_users()
        _print_namespaces(rows, users, settings)
        return 0

    if not args.email:
        print("FAILED: --email is required to change an assignment", file=sys.stderr)
        return 1

    # ``--email owner`` addresses the principal used when authentication is
    # disabled, which has no row in the users table.
    if args.email.strip().lower() == OWNER_PRINCIPAL_ID:
        user_id = OWNER_PRINCIPAL_ID
        account = OWNER_PRINCIPAL_ID
    else:
        user = await service.get_user_by_email(args.email)
        if user is None:
            print(f"FAILED: no account with email {args.email}", file=sys.stderr)
            return 1
        user_id = str(user.id)
        account = user.email

    if args.disable:
        row = await database.set_tenant_namespace_status(user_id, STATUS_DISABLED)
        if row is None:
            print(f"FAILED: {account} has no namespace assignment", file=sys.stderr)
            return 1
        print(f"{account} -> {row['namespace']} is now {row['status']}; the account "
              f"falls back to {settings.temporal_namespace}.")
        print("The namespace, its history and its name are kept -- re-enable with "
              "--enable, or reassign with --namespace.")
        return 0

    if args.enable:
        row = await database.get_tenant_namespace(user_id)
        if row is None:
            print(f"FAILED: {account} has no namespace assignment", file=sys.stderr)
            return 1
        if not await _provision_namespace(settings, row["namespace"], account, args.retention_days):
            return 1
        row = await database.set_tenant_namespace_status(user_id, STATUS_READY)
        print(f"{account} -> {row['namespace']} is now {row['status']}.")
        print("Restart the backend so it starts a worker for that namespace.")
        return 0

    try:
        namespace = validate_namespace(args.namespace)
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    try:
        # Written before the server call so a crash mid-provision leaves a
        # visible provisioning row rather than an orphan namespace.
        await database.upsert_tenant_namespace(user_id, namespace, status=STATUS_PROVISIONING)
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Assigned {account} -> {namespace} (status={STATUS_PROVISIONING})")

    if not await _provision_namespace(settings, namespace, account, args.retention_days):
        print(f"Left at status={STATUS_PROVISIONING}: {account} keeps using "
              f"{settings.temporal_namespace}. Re-run this command once Temporal "
              "is reachable.", file=sys.stderr)
        return 1

    await database.set_tenant_namespace_status(user_id, STATUS_READY)
    print(f"{namespace} is ready.")
    if not getattr(settings, "multi_tenant_namespaces", False):
        print("Note: MULTI_TENANT_NAMESPACES=false, so this assignment is not read "
              "at runtime yet.")
    print("Restart the backend so it starts a worker for that namespace.")
    return 0


async def _run(args: argparse.Namespace) -> int:
    service, database, settings = await _service()
    try:
        if args.command == "list":
            users = await service.list_users()
            _print_users(users)
            print()
            print(f"AUTH_MODE={settings.auth_mode}  (public registration: "
                  f"{'open to anyone' if settings.auth_mode == 'multi' else 'closed'})")
            return 0

        if args.command == "add":
            password = args.password or _generated_password()
            generated = args.password is None
            user, error = await service.provision_user(args.email, password, args.name)
            if user is None:
                print(f"FAILED: {error}", file=sys.stderr)
                return 1
            print(f"Created account id={user.id} email={user.email} owner={'yes' if user.is_owner else 'no'}")
            if generated:
                # Printed once and never stored in cleartext -- only the bcrypt
                # hash reaches the database. Deliver it over a private channel
                # and have the user change it after first login.
                print(f"Generated password: {password}")
                print("Share it out of band; it cannot be recovered later, only reset.")
            return 0

        if args.command == "passwd":
            password = args.password or _generated_password()
            generated = args.password is None
            user, error = await service.set_user_password(args.email, password)
            if user is None:
                print(f"FAILED: {error}", file=sys.stderr)
                return 1
            print(f"Password reset for {user.email}")
            if generated:
                print(f"New password: {password}")
            print("Existing sessions stay valid until their JWT expires; disable the "
                  "account instead if access must stop now.")
            return 0

        if args.command == "rename":
            user, error = await service.set_user_display_name(args.email, args.name)
            if user is None:
                print(f"FAILED: {error}", file=sys.stderr)
                return 1
            print(f"{user.email} is now displayed as {user.display_name}")
            print("An open session keeps the old name until the next login "
                  "(the name rides in the JWT).")
            return 0

        if args.command == "remove":
            email, error = await service.delete_user(args.email)
            if email is None:
                print(f"FAILED: {error}", file=sys.stderr)
                return 1
            print(f"Deleted account {email}")
            return 0

        if args.command in ("enable", "disable"):
            user, error = await service.set_user_active(args.email, args.command == "enable")
            if user is None:
                print(f"FAILED: {error}", file=sys.stderr)
                return 1
            print(f"Account {user.email} is now {'active' if user.is_active else 'disabled'}")
            return 0

        if args.command == "namespace":
            return await _run_namespace(args, service, database, settings)

        print(f"unknown command: {args.command}", file=sys.stderr)
        return 2
    finally:
        await database.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="manage_users.py",
        description="Add and maintain login accounts on a deployed OpenCompany instance.",
        epilog="Reminder: accounts share one workflow store and one credential store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show every account")

    add = sub.add_parser("add", help="create an account (bypasses the closed /register form)")
    add.add_argument("--email", required=True)
    add.add_argument("--name", required=True, help="display name, 100 characters or fewer")
    add.add_argument("--password", help="omit to generate a strong one and print it once")

    passwd = sub.add_parser("passwd", help="reset an account password")
    passwd.add_argument("--email", required=True)
    passwd.add_argument("--password", help="omit to generate a strong one and print it once")

    rename = sub.add_parser("rename", help="change an account display name")
    rename.add_argument("--email", required=True)
    rename.add_argument("--name", required=True, help="new display name, 100 characters or fewer")

    for name, help_text in (
        ("disable", "block sign-in (reversible, keeps the row)"),
        ("enable", "restore sign-in"),
        ("remove", "delete the account row -- prefer disable"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--email", required=True)

    ns = sub.add_parser(
        "namespace",
        help=(
            "assign a Temporal namespace to an account "
            "(requires MULTI_TENANT_NAMESPACES=true to take effect)"
        ),
    )
    ns.add_argument("--email", default=None, help="account email, or 'owner' for the auth-disabled principal")
    ns_action = ns.add_mutually_exclusive_group()
    ns_action.add_argument("--namespace", default=None, metavar="NAME", help="assign and provision a namespace")
    ns_action.add_argument("--disable", action="store_true", default=False, help="route account back to the default namespace (keeps the row)")
    ns_action.add_argument("--enable", action="store_true", default=False, help="re-provision and re-enable a previously disabled namespace")
    ns.add_argument(
        "--retention-days",
        type=int,
        default=7,
        metavar="N",
        dest="retention_days",
        help=(
            "closed-workflow retention for the new namespace in days (default: 7). "
            "Temporal rejects values below 1. Retention reaps only CLOSED executions -- "
            "running/paused deployments are never affected."
        ),
    )

    args = parser.parse_args()
    _bootstrap_path()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
