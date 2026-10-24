"""Phase 3 integration tests: the page lifecycle against the real HAXcms instance.

Covers the PLAN Phase 3 integration list: create -> get by id and by slug -> rename (the
slug regenerates under Pathauto) -> an explicit slug sticks across later title changes ->
unpublish hides the page from the anonymous outline (raw unauthenticated GET) -> delete;
plus the on-disk side effects (`site.json` items and `pages/<id>/index.html`).
"""

from __future__ import annotations

import pytest

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.services import pages as pages_service
from tests.harness.haxcms_runtime import HaxcmsRuntime
from tests.harness.site_reads import public_titles

pytestmark = pytest.mark.integration


def _manifest_ids(haxcms: HaxcmsRuntime, site: str) -> list[str]:
    return [str(item["id"]) for item in haxcms.read_site_json(site)["items"]]


async def test_page_lifecycle(client: HaxcmsClient, site: str, haxcms: HaxcmsRuntime) -> None:
    created = await pages_service.create_page(
        client, site, "Lesson One", content_html="<p>Lesson material.</p>"
    )
    assert created.id
    assert created.title == "Lesson One"
    assert created.slug == "lesson-one"  # Pathauto slugifies the title
    assert created.published is True

    # disk: the manifest gained the item and the page file exists with the seeded content
    assert created.id in _manifest_ids(haxcms, site)
    assert (haxcms.site_dir(site) / "pages" / created.id / "index.html").is_file()
    assert "Lesson material." in haxcms.read_page_html(site, created.id)

    # get by id and by slug return the same page
    by_id = await pages_service.find_page(client, site, created.id)
    by_slug = await pages_service.find_page(client, site, "lesson-one")
    assert by_id.id == by_slug.id == created.id

    # renaming under Pathauto regenerates the slug
    renamed = await pages_service.update_page_details(client, site, created.id, title="Lesson Two")
    assert renamed.title == "Lesson Two"
    assert renamed.slug == "lesson-two"

    # an explicit slug sets overridePathauto and survives later title changes
    pinned = await pages_service.update_page_details(
        client, site, created.id, slug="custom-landing"
    )
    assert pinned.slug == "custom-landing"
    assert pinned.metadata.override_pathauto is True
    retitled = await pages_service.update_page_details(
        client, site, created.id, title="Lesson Three"
    )
    assert retitled.title == "Lesson Three"
    assert retitled.slug == "custom-landing"

    # unpublish: gone from the anonymous outline (raw unauthenticated GET) but still
    # visible to the bearer caller
    unpublished = await pages_service.update_page_details(client, site, created.id, published=False)
    assert unpublished.published is False
    assert "Lesson Three" not in public_titles(haxcms.base_url, site)
    bearer_view = await pages_service.find_page(client, site, created.id)
    assert bearer_view.published is False

    # delete: the record comes back, the manifest loses the item, lookups 404
    deleted = await pages_service.delete_page(client, site, created.id)
    assert deleted.id == created.id
    assert created.id not in _manifest_ids(haxcms, site)
    with pytest.raises(HaxcmsMcpError) as excinfo:
        await pages_service.find_page(client, site, created.id)
    assert excinfo.value.code is ErrorCode.NOT_FOUND
