"""aws-cli adapter -- still a placeholder.

The ``cli/terraform/aws/`` module has landed (validated t3.micro setup), but
this adapter has not been wired to it yet. It implements the ``ProviderCli``
shape so the resolver/wiring is uniform, and aborts with a clear message
(exit 1) when selected. The real adapter will mirror gcp.py: ``aws sts
get-caller-identity`` for auth, the default credential chain for Terraform,
region from ``aws configure get region`` / ``$AWS_REGION``, and the existing
security-group + EC2 instance module.
"""

from __future__ import annotations

import typer

from cli._common import error_block


class AwsCli:
    name = "aws"

    def _not_yet(self) -> None:
        error_block(
            "The aws provider is not implemented yet.",
            ["Use --provider gcp for now; the AWS module is a planned follow-on."],
        )
        raise typer.Exit(code=1)

    def check(self) -> None:
        self._not_yet()

    def authed_account(self) -> str | None:
        return None

    def resolve_context(self, *, region, zone, project) -> dict:
        self._not_yet()
        return {}

    def ensure_terraform_auth(self) -> None:
        self._not_yet()

    def enable_apis(self, ctx: dict) -> None:
        self._not_yet()

    def tfvars_extra(self, ctx: dict) -> dict:
        self._not_yet()
        return {}
