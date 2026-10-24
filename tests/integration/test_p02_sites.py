"""Phase 2 integration tests: the site lifecycle against the real HAXcms instance.

Covers the PLAN T2.6 integration list: create -> list -> get_site fields -> clone -> archive
(removed from the listing AND the folder moved to `_archived/` on disk), invalid theme ->
INVALID_ARGUMENT with no phantom site, duplicate-name behaviour (verified: the server silently
creates `<name>-1`), and the theme/skeleton reads.
"""

from __future__ import annotations

import contextlib
import secrets

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import sites as sites_service
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.site_reads import public_titles

pytestmark = pytest.mark.integration

SUFFIX = secrets.token_hex(3)


async def test_create_list_get_clone_archive(client: HaxcmsClient, haxcms: HaxcmsRuntime) -> None:
    name = f"p2-life-{SUFFIX}"
    created: list[str] = []
    try:
        detail = await sites_service.create_site(client, name, description="integration site")
        created.append(detail.name)
        assert detail.name == name
        assert detail.title == name  # upstream derives the title from the machine name
        assert detail.page_count == 1
        assert detail.counts is not None and detail.counts.items == 1
        assert detail.theme == "clean-one"
        assert detail.warnings is None

        entries = await sites_service.list_sites(client)
        assert name in [entry.name for entry in entries]

        fetched = await sites_service.get_site(client, name)
        assert fetched.name == name
        assert fetched.page_count == 1
        assert fetched.links is not None and "clone" in fetched.links

        cloned = await sites_service.clone_site(client, name)
        clone_name = str(cloned["name"])
        created.append(clone_name)
        assert clone_name != name
        assert clone_name.startswith(name)
        entries = await sites_service.list_sites(client)
        assert clone_name in [entry.name for entry in entries]

        archived = await sites_service.archive_site(client, name)
        assert archived["name"] == name
        assert archived["archived_name"] == name
        entries = await sites_service.list_sites(client)
        assert name not in [entry.name for entry in entries]
        # the folder moved out of _sites into _archived (nothing is deleted)
        assert not haxcms.site_dir(name).exists()
        assert haxcms.runtime_root is not None
        assert (haxcms.runtime_root / "_archived" / name).exists()
    finally:
        for site in created:
            with contextlib.suppress(HaxcmsMcpError):
                await sites_service.archive_site(client, site)


async def test_duplicate_name_gets_a_silent_suffix(client: HaxcmsClient) -> None:
    """Verified Phase 2 fact: creating an existing name returns 200 with `<name>-1`."""
    name = f"p2-dup-{SUFFIX}"
    created: list[str] = []
    try:
        first = await sites_service.create_site(client, name)
        created.append(first.name)
        second = await sites_service.create_site(client, name)
        created.append(second.name)
        assert second.name == f"{name}-1"
        assert second.warnings and any("already taken" in w for w in second.warnings)
    finally:
        for site in created:
            with contextlib.suppress(HaxcmsMcpError):
                await sites_service.archive_site(client, site)


async def test_invalid_theme_rejected_before_write(client: HaxcmsClient) -> None:
    """The service validates against the live registry: no POST, so no phantom site either.

    (Raw `POST sites` with an unknown theme 400s but leaves a phantom registration —
    verified Phase 2 fact; client-side validation avoids that upstream quirk.)
    """
    name = f"p2-bad-{SUFFIX}"
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await sites_service.create_site(client, name, theme="no-such-theme-xyz")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert "unknown theme" in excinfo.value.message
    entries = await sites_service.list_sites(client)
    assert name not in [entry.name for entry in entries]


async def test_theme_and_skeleton_reads(client: HaxcmsClient) -> None:
    themes = await sites_service.list_themes(client)
    machines = [theme.machine_name for theme in themes]
    assert "clean-one" in machines
    clean_one = next(theme for theme in themes if theme.machine_name == "clean-one")
    assert clean_one.name == "Clean One"

    skeletons = await sites_service.list_skeletons(client)
    names = [entry.machine_name for entry in skeletons]
    assert "online-course-clean-one" in names
    course = next(entry for entry in skeletons if entry.machine_name == "online-course-clean-one")
    assert course.category == ["Course"]
    assert course.title == "Online Course"

    detail = await sites_service.get_skeleton(client, "online-course-clean-one")
    assert detail.meta.title == "Online Course"
    assert detail.site["theme"] == "clean-one"
    items = detail.build.get("items")
    assert isinstance(items, list) and items

    with pytest.raises(HaxcmsMcpError) as excinfo:
        await sites_service.get_skeleton(client, "no-such-skeleton-xyz")
    assert excinfo.value.code is ErrorCode.NOT_FOUND


async def test_create_from_skeleton_builds_the_journey_pages(
    client: HaxcmsClient, haxcms: HaxcmsRuntime
) -> None:
    name = f"p2-sk-{SUFFIX}"
    try:
        detail = await sites_service.create_site_from_skeleton(
            client, "online-course-clean-one", name
        )
        assert detail.name == name
        # the skeleton's description and pages win (verified: 5 pages, course description)
        assert detail.page_count == 5
        assert detail.counts is not None and detail.counts.items == 5
        assert "online course" in detail.description.lower()
        titles = public_titles(haxcms.base_url, name)
        assert "Syllabus" in titles
        assert any(title.startswith("Lesson 1") for title in titles)
    finally:
        with contextlib.suppress(HaxcmsMcpError):
            await sites_service.archive_site(client, name)
