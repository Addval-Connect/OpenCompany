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

    args = parser.parse_args()
    _bootstrap_path()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
