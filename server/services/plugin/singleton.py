"""Service-singleton mixin for plugin-owned long-lived services.

Replaces the per-plugin ``_instance`` + ``get_instance()`` boilerplate
that each ``nodes/<plugin>/_service.py`` currently re-implements.
Pre-T inventory (Wave 11.I plan):

- ``nodes/telegram/_service.py:TelegramService`` -- ``_instance`` + sync
  ``get_instance`` + async ``reset_instance`` (custom — disconnects).
- ``nodes/email/_service.py:EmailService`` -- ``_instance`` + sync
  ``get_instance``, no reset.
- ``nodes/browser/_service.py`` -- module-level ``_instance`` global,
  no class-level state (different shape, kept bespoke).
- ``nodes/whatsapp/_service.py`` -- supervisor-aware singleton via
  ``BaseProcessSupervisor``, kept bespoke (different lifecycle).

Subclasses get :meth:`instance` for free. They override
:meth:`reset_instance` only if there's a side effect on reset
(Telegram disconnects the bot poll loop; that stays per-plugin).
"""

from __future__ import annotations

from typing import ClassVar, Dict, Optional, TypeVar

T = TypeVar("T", bound="ServiceSingleton")


class ServiceSingleton:
    """Mixin: per-(class, namespace) lazy singleton.

    Each subclass that opts in gets its own instance store lazily
    populated on first :meth:`instance` call. The Python attribute
    rules guarantee per-class isolation (read climbs MRO, write goes
    to the immediate class), so ``A.instance()`` and ``B.instance()``
    return distinct singletons even though both inherit the same
    declaration here.

    Instances are keyed by NAMESPACE: long-lived plugin services (bot
    connections, SDK sessions) hold per-tenant state — credentials,
    pollers, owner ids — and a process-wide singleton made every tenant
    share whichever tenant's bot connected last. ``instance()`` resolves
    the namespace from the active-namespace ContextVar when not given,
    so a call inside a sealed request/activity context lands on that
    tenant's instance automatically.

    Usage::

        class TelegramService(ServiceSingleton):
            ...

        # module-level helper consumed by handler files:
        def get_telegram_service() -> TelegramService:
            return TelegramService.instance()

    Subclasses may also override :meth:`reset_instance` to add side
    effects (e.g. tear down a bot polling loop) before clearing.
    """

    _instance: ClassVar[Optional["ServiceSingleton"]] = None  # legacy slot (pre-namespace shape)
    _instances: ClassVar[Optional[Dict[str, "ServiceSingleton"]]] = None

    @classmethod
    def _namespace_instances(cls) -> Dict[str, "ServiceSingleton"]:
        """Per-CLASS instance dict — never inherited from the base."""
        instances = cls.__dict__.get("_instances")
        if instances is None:
            instances = {}
            cls._instances = instances
        return instances

    @classmethod
    def instance(cls: type[T], *, namespace: Optional[str] = None) -> T:
        """Return the (class, namespace) singleton, constructing on first call.

        ``namespace=None`` resolves the active-namespace ContextVar — so
        handlers running inside a sealed request/activity context get
        their own tenant's instance. Pass an explicit namespace when the
        caller's context cannot be trusted to carry one.
        """
        if namespace is None:
            from core.namespace_context import get_active_namespace

            namespace = get_active_namespace() or "default"
        instances = cls._namespace_instances()
        inst = instances.get(namespace)
        if inst is None:
            inst = cls()
            instances[namespace] = inst
        return inst  # type: ignore[return-value]

    @classmethod
    def reset_instance(cls, namespace: Optional[str] = None) -> None:
        """Drop the cached singleton(s). Override for async / cleanup
        flows; the default is a sync no-side-effect clear.

        ``namespace=None`` drops EVERY namespace's instance (process
        shutdown / full invalidation); a namespace drops only that
        tenant's, leaving the others live."""
        instances = cls.__dict__.get("_instances")
        if instances:
            if namespace is None:
                instances.clear()
            else:
                instances.pop(namespace, None)
        if cls.__dict__.get("_instance") is not None:
            cls._instance = None
