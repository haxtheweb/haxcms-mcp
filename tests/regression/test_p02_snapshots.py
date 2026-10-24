"""Phase 2 regression snapshots: the create-site payload goldens (PLAN §6.4, T2.6).

The tool-schema snapshot (test_p00_snapshots.py) grows the nine site tools automatically —
update both deliberately with `pytest --snapshot-update`.
"""

from __future__ import annotations

from typing import Any

import pytest

from haxcms_mcp.services.sites import build_create_payload
from tests.harness.snapshots import assert_or_update_snapshot

pytestmark = pytest.mark.regression


def _goldens() -> dict[str, Any]:
    """Deterministic payloads: the item id is injected so the golden never churns."""
    return {
        "blank_defaults": build_create_payload("my-course", home_id="item-home-golden"),
        "blank_custom": build_create_payload(
            "my-course",
            description="An online course",
            theme="clean-portfolio",
            license="by-nc",
            first_page_title="Welcome",
            first_page_content="<p>Welcome to the course.</p>",
            home_id="item-home-golden",
        ),
        "from_skeleton": build_create_payload(
            "my-course",
            description="",
            skeleton="online-course-clean-one",
        ),
    }


def test_create_site_payloads(request: pytest.FixtureRequest) -> None:
    update = bool(request.config.getoption("--snapshot-update", default=False))
    assert_or_update_snapshot("create_site_payloads", _goldens(), update=update)
