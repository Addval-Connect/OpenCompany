"""Which Temporal namespace a login account executes in.

This module is the **only** place that knows the account -> namespace
mapping. Everything else (the client registry, the worker bootstrap, the
event dispatcher, the workflow-control store) asks here and takes the
answer, so turning the feature on or off is one flag in one file rather
than a predicate duplicated across the execution path.

Three rules the callers depend on:

1. With ``MULTI_TENANT_NAMESPACES=false`` the answer is always
   ``Settings.temporal_namespace``. No database read happens at all, so
   the flag off is byte-identical to the pre-feature behaviour.
2. An account with no mapping row resolves to the default namespace.
   Provisioning is manual by design (``scripts/manage_users.py
   namespace``), so "not provisioned yet" must behave like today rather
   than point at a namespace no worker polls.
3. A mapping whose ``status`` is not ``ready`` also resolves to the
   default namespace. ``provisioning`` means the namespace may not exist
   on the server yet; ``disabled`` means the operator revoked it while
   keeping the row so the namespace stays reserved and its history stays
   attributable.

What is deliberately NOT tolerated: a database failure. That propagates.
Swallowing it would resolve a tenant to the shared namespace, which is
the exact isolation break the feature exists to prevent — and it would
do so silently, at execution time. Read the section note in
``core/database.py`` next to the tenant CRUD helpers for the other half
of this argument.

Unrelated to :class:`models.database.IdentitySequence.namespace`, which
is a counter bucket name.
"""

from __future__ import annotations

import re
from typing import Any, Final, Optional

from core.logging import get_logger

logger = get_logger(__name__)


# Temporal namespace names are DNS-ish: Temporal itself is permissive,
# but the name shows up in workflow ids, worker identities and Web UI
# URLs, so pin it to the conservative shape rather than discovering the
# edge cases in production. 3-63 chars, lowercase start, no trailing
# hyphen.
NAMESPACE_PATTERN: Final[str] = r"^[a-z][a-z0-9-]{1,61}[a-z0-9]$"

_NAMESPACE_RE: Final[re.Pattern[str]] = re.compile(NAMESPACE_PATTERN)

# ``default`` is the shared namespace every unmapped account lands in —
# assigning it to one tenant would silently hand that tenant everyone
# else's executions. ``temporal-system`` is the server's own internal
# namespace.
RESERVED_NAMESPACES: Final[frozenset[str]] = frozenset({"default", "temporal-system"})

STATUS_PROVISIONING: Final[str] = "provisioning"
STATUS_READY: Final[str] = "ready"
STATUS_DISABLED: Final[str] = "disabled"
TENANT_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_PROVISIONING, STATUS_READY, STATUS_DISABLED}
)


def is_valid_namespace(value: Any) -> bool:
    """True if ``value`` is a well-shaped, non-reserved namespace name.

    Non-string input is invalid rather than an error — operator CLI
    arguments and stored rows both arrive here unvalidated.
    """
    if not isinstance(value, str):
        return False
    if value in RESERVED_NAMESPACES:
        return False
    return bool(_NAMESPACE_RE.fullmatch(value))


def validate_namespace(value: Any) -> str:
    """Return ``value`` unchanged, or raise ``ValueError`` explaining why not.

    For the operator CLI, where a rejected name needs a sentence rather
    than a boolean.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("namespace must be a non-empty string")
    if value in RESERVED_NAMESPACES:
        raise ValueError(
            f"namespace {value!r} is reserved — pick a tenant-specific name "
            f"(reserved: {', '.join(sorted(RESERVED_NAMESPACES))})"
        )
    if not _NAMESPACE_RE.fullmatch(value):
        raise ValueError(
            f"namespace {value!r} must match {NAMESPACE_PATTERN} "
            "(3-63 chars, lowercase letters/digits/hyphens, no leading digit "
            "or trailing hyphen)"
        )
    return value


async def resolve_tenant_namespace(
    user_id: Optional[str],
    *,
    database: Any,
    settings: Any,
) -> str:
    """The Temporal namespace ``user_id`` executes in.

    ``database`` and ``settings`` are passed in rather than pulled from
    the container so this stays a pure function of its inputs (and so
    tests do not need a wired container).

    Raises whatever the database raises — see the module docstring.
    """
    default_namespace = settings.temporal_namespace

    if not getattr(settings, "multi_tenant_namespaces", False):
        return default_namespace
    if not user_id:
        return default_namespace

    row = await database.get_tenant_namespace(str(user_id))
    if row is None:
        return default_namespace

    status = row.get("status")
    if status != STATUS_READY:
        logger.debug(
            "Tenant namespace not ready; using default",
            user_id=str(user_id),
            namespace=row.get("namespace"),
            status=status,
        )
        return default_namespace

    namespace = row.get("namespace")
    if not is_valid_namespace(namespace):
        # A malformed stored value is an operator error, not a routing
        # decision — refuse rather than guess.
        raise ValueError(
            f"tenant namespace {namespace!r} for user_id {user_id!r} is malformed; "
            "re-assign it with `python scripts/manage_users.py namespace`"
        )
    return namespace


__all__ = [
    "NAMESPACE_PATTERN",
    "RESERVED_NAMESPACES",
    "STATUS_DISABLED",
    "STATUS_PROVISIONING",
    "STATUS_READY",
    "TENANT_STATUSES",
    "is_valid_namespace",
    "resolve_tenant_namespace",
    "validate_namespace",
]
