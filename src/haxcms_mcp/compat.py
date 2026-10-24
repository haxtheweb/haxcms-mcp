"""Startup compatibility check between this MCP's vendored HAXcms spec and the live instance.

The MCP is a typed client of the HAXcms HTTP API, so it breaks when that API changes. HAXcms
serves its system OpenAPI document unauthenticated at `GET /system/api/v1/openapi` (the raw
`system-spec.yaml`), and `info.version` in it is a constant `1.0.0` — useless for drift. The
reliable signal is a content hash: `generated/spec_info.py` records the SHA-256 of the specs
this build vendored, and `CompatChecker` compares it with the hash of what the instance serves.

A mismatch is a WARNING (logged once, surfaced by `get_server_info`), never a failure: most
spec edits are descriptions and examples that do not affect behaviour.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Literal

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.errors import HaxcmsMcpError
from haxcms_mcp.generated import spec_info
from haxcms_mcp.logging import get_logger
from haxcms_mcp.spec_hash import spec_sha256

log = get_logger("compat")

CHECK_TIMEOUT_S = 10.0

Status = Literal["match", "mismatch", "unavailable"]


@dataclass(frozen=True)
class SpecCompatibility:
    """Result of comparing the instance's served system spec with the vendored one."""

    status: Status
    vendored_ref: str
    expected_sha256: str
    actual_sha256: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def vendored_ref() -> str:
    return f"HAXcms NodeJS {spec_info.HAXCMS_VERSION} @ {spec_info.HAXCMS_COMMIT}"


async def check_spec_compatibility(client: HaxcmsClient) -> SpecCompatibility:
    """Fetch the instance's system spec and compare its hash with the vendored one."""
    ref = vendored_ref()
    expected = spec_info.SYSTEM_SPEC_SHA256
    try:
        response = await client.request(
            "GET",
            client.sys("openapi"),
            auth="none",
            accept="application/yaml",
            timeout=CHECK_TIMEOUT_S,
            no_retry=True,
        )
    except HaxcmsMcpError as exc:
        return SpecCompatibility("unavailable", ref, expected, detail=exc.formatted)
    if response.status_code != 200:
        return SpecCompatibility(
            "unavailable",
            ref,
            expected,
            detail=f"GET system/api/v1/openapi answered HTTP {response.status_code}",
        )
    actual = spec_sha256(response.content)
    if actual == expected:
        return SpecCompatibility("match", ref, expected, actual)
    return SpecCompatibility(
        "mismatch",
        ref,
        expected,
        actual,
        detail=(
            "the instance serves a different system OpenAPI spec than this server was built "
            "against; some tools may misbehave. Upgrade/downgrade HAXcms or this server, and "
            "see the README's supported HAXcms range"
        ),
    )


class CompatChecker:
    """Runs the check once per process (and again only while the instance was unreachable)."""

    def __init__(self, client: HaxcmsClient) -> None:
        self._client = client
        self._lock = asyncio.Lock()
        self._result: SpecCompatibility | None = None

    async def result(self) -> SpecCompatibility:
        async with self._lock:
            if self._result is None:
                outcome = await check_spec_compatibility(self._client)
                self._log(outcome)
                if outcome.status != "unavailable":
                    self._result = outcome  # an unreachable instance is retried next time
                return outcome
            return self._result

    def _log(self, outcome: SpecCompatibility) -> None:
        if outcome.status == "mismatch":
            log.warning(
                "HAXcms spec mismatch: the instance's system OpenAPI hash %s differs from the "
                "vendored %s (%s). %s",
                (outcome.actual_sha256 or "")[:12],
                outcome.expected_sha256[:12],
                outcome.vendored_ref,
                outcome.detail,
            )
        elif outcome.status == "unavailable":
            log.info("HAXcms spec compatibility check skipped: %s", outcome.detail)
        else:
            log.info("HAXcms spec matches the vendored %s", outcome.vendored_ref)
