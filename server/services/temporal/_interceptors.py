"""Wave 17.3: Temporal SDK worker interceptors for retry observability.

On a local-PC deployment the worker dies without SIGTERM (laptop sleep,
hard kill, battery). Temporal re-dispatches the interrupted activity on
the next poll — invisibly, unless something logs the attempt number.
These interceptors give the operator log a structured
``activity_retry`` line whenever ``activity.info().attempt > 1`` so
"first attempt" vs "re-dispatch after worker restart" is
distinguishable without opening the Temporal Web UI.

Registration: both Worker constructions in ``worker.py`` pass
``interceptors=[ObservabilityWorkerInterceptor()]``.

Replay-safety contract (per
https://docs.temporal.io/develop/python/workers/interceptors):
workflow inbound interceptor methods also execute during Event-History
replay. Side effects there would diverge the replay from the recorded
history, so ``WorkflowObservabilityInterceptor`` guards every log call
with ``workflow.unsafe.is_replaying()``. Activity interceptors run only
on live executions — no guard needed.
"""

from __future__ import annotations

from typing import Any, Optional, Type

from temporalio import activity, workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from core.logging import get_logger

logger = get_logger(__name__)


class ActivityTenantContextInterceptor(ActivityInboundInterceptor):
    """Seal the tenant-namespace ContextVar for the activity body.

    The active-namespace ContextVar does not cross the Temporal
    boundary: activities run on worker threads where no HTTP middleware
    ever ran. The workflow payload carries ``credential_customer_id``
    (transport, not an API — see ``docs-internal/multitenant.md`` §1)
    and this interceptor turns it back into the ContextVar the DB /
    credential pools read, BEFORE the activity body executes.

    This is the single worker-side setter. Activity bodies, services and
    nodes must never set the namespace themselves — every production
    incident logged in multitenant.md §6 was a call site that had to
    remember to do it and didn't.

    Activities whose payload carries no key (progress broadcasts,
    tool refreshes, skill clears) are stamped with the default — the
    same ambient value they observed before this interceptor existed.
    """

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        from constants import normalize_credential_ns
        from core.namespace_context import set_active_namespace

        tenant = None
        for arg in input.args or ():
            if isinstance(arg, dict) and arg.get("credential_customer_id"):
                tenant = arg["credential_customer_id"]
                break
        set_active_namespace(normalize_credential_ns(tenant))
        return await self.next.execute_activity(input)


class ActivityObservabilityInterceptor(ActivityInboundInterceptor):
    """Log start / retry / end (with outcome) for every activity."""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        extra = {
            "activity_name": info.activity_type,
            "activity_id": info.activity_id,
            "workflow_id": info.workflow_id,
            "attempt": info.attempt,
        }
        if info.attempt > 1:
            # Re-dispatch: prior attempt died (worker crash / laptop
            # sleep / timeout) or failed retryably. WARN so ops can
            # count these without DEBUG noise.
            logger.warning("activity_retry", **extra)
        else:
            logger.debug("activity_start", **extra)
        try:
            result = await self.next.execute_activity(input)
        except Exception as exc:
            logger.warning(
                "activity_end",
                outcome="failure",
                error=type(exc).__name__,
                **extra,
            )
            raise
        logger.debug("activity_end", outcome="success", **extra)
        return result


class WorkflowObservabilityInterceptor(WorkflowInboundInterceptor):
    """Log workflow starts — guarded so replays stay deterministic."""

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        if not workflow.unsafe.is_replaying():
            wf_info = workflow.info()
            logger.info(
                "workflow_start",
                workflow_type=wf_info.workflow_type,
                workflow_id=wf_info.workflow_id,
                run_id=wf_info.run_id,
                attempt=wf_info.attempt,
            )
        return await self.next.execute_workflow(input)


class TenantContextWorkerInterceptor(Interceptor):
    """Worker-level wiring for the tenant-namespace interceptor.

    Register FIRST in the interceptors list so the ContextVar is sealed
    before observability logging and the activity body run.
    """

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return ActivityTenantContextInterceptor(next)


class ObservabilityWorkerInterceptor(Interceptor):
    """Worker-level wiring: one instance shared by all Workers."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return ActivityObservabilityInterceptor(next)

    def workflow_interceptor_class(self, input: WorkflowInterceptorClassInput) -> Optional[Type[WorkflowInboundInterceptor]]:
        return WorkflowObservabilityInterceptor
