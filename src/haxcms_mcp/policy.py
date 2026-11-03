"""The HAXcms instance's own MCP policy (Phase 0 of the OAuth plan, haxtheweb/issues#3140).

HAXcms carries `config.mcp = {enabled, readOnly}` (disabled by default on HAXiam-managed
deployments, read-only by default everywhere) and publishes it on the open system
discovery route, `GET /system/api/v1` -> `data.mcp`. This server obeys it:

* `enabled: false` -> every tool, resource and prompt is refused with `MCP_DISABLED`;
  only `get_server_info` still answers, so an operator can see why.
* `readOnly: true` -> Read-Only Mode is on, whatever `HAXCMS_MCP_READ_ONLY` says.
  (The local setting can only make the server stricter, never looser.)

An instance that does not publish the field yet (HAXcms before this change) is treated
as "no policy": the local settings decide, and a warning says so. An unreachable instance
is not a verdict either: the policy is fetched again on the next call.

This is cooperative enforcement by a well-behaved client, not a security boundary: HAXcms
itself enforces MCP tokens once the OAuth work (Phase 1) lands.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.generated import system_routes as routes
from haxcms_mcp.logging import get_logger

logger = get_logger(__name__)

POLICY_TTL_S = 60.0  # how long a fetched policy is trusted before asking again
POLICY_TIMEOUT_S = 10.0

PolicyState = Literal["published", "unpublished", "unavailable"]


@dataclass(frozen=True)
class InstancePolicy:
    state: PolicyState
    enabled: bool | None = None  # None unless state == "published"
    read_only: bool | None = None
    detail: str | None = None

    @property
    def disabled(self) -> bool:
        return self.state == "published" and self.enabled is False

    @property
    def forces_read_only(self) -> bool:
        return self.state == "published" and self.read_only is True

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state}
        if self.state == "published":
            out["enabled"] = self.enabled
            out["read_only"] = self.read_only
        if self.detail:
            out["detail"] = self.detail
        return out


def parse_policy(body: Any) -> InstancePolicy:
    """`{status, data: {..., mcp: {enabled, readOnly}}}` -> InstancePolicy."""
    data = body.get("data") if isinstance(body, dict) else None
    mcp = data.get("mcp") if isinstance(data, dict) else None
    if not isinstance(mcp, dict):
        return InstancePolicy(
            "unpublished",
            detail="this HAXcms does not publish an MCP policy yet; local settings apply",
        )
    # strict booleans, failing safe: anything but a real `true` is "not enabled", and
    # anything but a real `false` is "read-only" (mirrors HAXcms isMcpEnabled/ReadOnly)
    enabled = mcp.get("enabled") is True
    read_only = mcp.get("readOnly") is not False or not enabled
    return InstancePolicy("published", enabled=enabled, read_only=read_only)


async def fetch_policy(client: HaxcmsClient) -> InstancePolicy:
    try:
        response = await client.call(
            routes.system_api_discovery(), timeout=POLICY_TIMEOUT_S, no_retry=True
        )
    except Exception as exc:  # noqa: BLE001 - an unreachable instance is not a verdict
        return InstancePolicy("unavailable", detail=f"discovery unreachable ({type(exc).__name__})")
    if response.status_code != 200:
        return InstancePolicy(
            "unavailable", detail=f"discovery answered HTTP {response.status_code}"
        )
    try:
        return parse_policy(response.json())
    except ValueError:
        return InstancePolicy("unavailable", detail="discovery did not answer JSON")


class PolicyChecker:
    """Fetches the policy at most once per POLICY_TTL_S (unavailable: every call)."""

    def __init__(self, client: HaxcmsClient, *, clock: Any = time.monotonic) -> None:
        self._client = client
        self._clock = clock
        self._lock = asyncio.Lock()
        self._policy: InstancePolicy | None = None
        self._fetched_at = 0.0

    async def current(self) -> InstancePolicy:
        async with self._lock:
            fresh = self._policy is not None and (self._clock() - self._fetched_at < POLICY_TTL_S)
            if fresh and self._policy is not None and self._policy.state != "unavailable":
                return self._policy
            policy = await fetch_policy(self._client)
            if policy != self._policy:
                _log_change(policy)
            self._policy = policy
            self._fetched_at = self._clock()
            return policy


def _log_change(policy: InstancePolicy) -> None:
    if policy.disabled:
        logger.error(
            "this HAXcms instance has MCP turned off (config.mcp.enabled is false): every "
            "tool call will be refused until the instance's operator enables it"
        )
    elif policy.forces_read_only:
        logger.warning(
            "this HAXcms instance allows MCP read-only (config.mcp.readOnly): write tools "
            "are refused"
        )
    elif policy.state == "published":
        logger.info("this HAXcms instance allows MCP reads and writes")
    elif policy.state == "unpublished":
        logger.warning("%s", policy.detail)
    else:
        logger.info("instance MCP policy not known yet: %s", policy.detail)
