"""Typed System API endpoint helpers (PLAN Phase 1 T1.6, Phase 2 T2.2).

Where each call goes (method, path, required auth) comes from the routes generated from the
spec (`generated/system_routes.py`, ADR-0005); this module owns bodies and response shapes.
Header requirements follow the `security:` blocks in `specs/system-spec.yaml` (verified live in
Phase 0/2): login/refresh/logout/connection-settings are open; `sites` (list/info/create/clone/
archive), `status`, `system/version`, `session/user`, and `themes` require bearer +
X-HAXCMS-User-Token; `skeletons` and `skeletons/{name}` require bearer only. Phase 7 adds the
import routes (`actions/import-*`, `site/import/{platform}`) and the twelve converter actions —
also bearer + user token; their errors carry `data.error` instead of `data.message`.
"""

from __future__ import annotations

from typing import Any, Final

from haxcms_mcp.client import HaxcmsClient
from haxcms_mcp.client.envelope import (
    error_from_response,
    unwrap,
    unwrap_dict,
    unwrap_full,
    unwrap_list,
)
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.generated import system_routes as routes
from haxcms_mcp.generated.route import Route
from haxcms_mcp.models.site import SiteList


async def login(client: HaxcmsClient, username: str, password: str) -> dict[str, Any]:
    """POST session/login -> full body `{status, jwt}` (cookies land in the client jar)."""
    response = await client.call(
        routes.session_login(),
        json={"username": username, "password": password},
        no_retry=True,
    )
    return unwrap_full(response)


async def refresh(client: HaxcmsClient) -> dict[str, Any]:
    """GET session/refresh using the cookie jar -> `{status, jwt}` + rotated cookie."""
    response = await client.call(routes.session_refresh_get(), no_retry=True)
    return unwrap_full(response)


async def logout(client: HaxcmsClient) -> Any:
    """POST session/logout -> "loggedout"."""
    response = await client.call(routes.session_logout(), no_retry=True)
    return unwrap(response)


async def session(client: HaxcmsClient) -> Any:
    """GET session (anonymous probe route; bearer attached when one is held)."""
    response = await client.call(
        routes.session_auth_get(), auth="bearer"
    )  # open route; bearer names the user
    return unwrap(response)


async def session_user(client: HaxcmsClient) -> Any:
    """GET session/user -> active user profile (bearer + user token)."""
    response = await client.call(routes.session_user_get())
    return unwrap(response)


async def status(client: HaxcmsClient) -> Any:
    """GET status -> environment diagnostics (includes the upload limit)."""
    response = await client.call(routes.system_status_get())
    return unwrap(response)


async def version(client: HaxcmsClient) -> Any:
    """GET system/version -> installed HAXcms version details."""
    response = await client.call(routes.system_version_get())
    return unwrap(response)


async def list_sites(client: HaxcmsClient) -> SiteList:
    """GET sites -> typed site listing (bearer + user token; verified fact, Phase 0)."""
    response = await client.call(routes.list_sites())
    return SiteList.from_api(unwrap(response))


async def site_info(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """GET sites/{name} -> `{id, name, title, description, location, metadata, links}`.

    `metadata.pageCount` is the page count; `links` names every system operation for the site.
    """
    response = await client.call(routes.site_info_get(site))
    return unwrap_dict(response)


async def create_site(client: HaxcmsClient, payload: dict[str, Any]) -> dict[str, Any]:
    """POST sites -> the created site's first item (JSONOutlineSchemaItem).

    The ACTUAL site name is at `metadata.site.name` — on a duplicate request the server silently
    creates `<name>-1` (Phase 2 probe), so callers must read the name back, not assume it.
    """
    response = await client.call(routes.create_site(), json=payload)
    return unwrap_dict(response)


async def clone_site(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """POST sites/{name}/clone -> `{detail: "/_sites/<new>", name: "<new>"}` (Phase 2 probe)."""
    response = await client.call(routes.clone_site(site), json={"site": {"name": site}})
    return unwrap_dict(response)


async def archive_site(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """POST sites/{name}/archive -> `{name, archivedName, detail: "Site archived"}`."""
    response = await client.call(routes.archive_site(site), json={"site": {"name": site}})
    return unwrap_dict(response)


async def list_themes(client: HaxcmsClient) -> list[dict[str, Any]]:
    """GET themes -> LIST of theme records (API-REF §3.5 said "map"; live it is a list)."""
    response = await client.call(routes.system_themes_get())
    return unwrap_list(response)


async def list_skeletons(client: HaxcmsClient) -> list[dict[str, Any]]:
    """GET skeletons -> LIST of flat skeleton records (bearer only per spec security block)."""
    response = await client.call(routes.system_skeletons_get())
    return unwrap_list(response)


async def get_skeleton(client: HaxcmsClient, name: str) -> dict[str, Any]:
    """GET skeletons/{name} -> `{meta, site, build, ...}` full skeleton detail (bearer only)."""
    response = await client.call(routes.system_skeleton_detail_get(name))
    return unwrap_dict(response)


# --- Phase 7: imports and converter actions (T7.2) --------------------------------------------
# All routes below are bearer + X-HAXCMS-User-Token per the spec security blocks (live-probed:
# bearer-only gets the 403 "X-HAXCMS-User-Token header is required for this endpoint").

# import kind -> spec operationId (paths come from the generated routes)
IMPORT_KIND_ROUTES: Final[dict[str, str]] = {
    kind: f"import{kind.capitalize()}" for kind in ("docx", "pptx", "html", "xlsx", "pdf")
}

# operationId -> path for the twelve generated converters (ADR-0002; scripts/gen_tools.py
# derives the same table from specs/system-spec.yaml, pinned 26.8.1).
ACTION_ROUTES: Final[frozenset[str]] = frozenset(
    {
        "docxToHtml",
        "htmlToDocx",
        "mdToHtml",
        "htmlToMd",
        "prettyHtml",
        "jsonToYaml",
        "yamlToJson",
        "htmlToPdf",
        "xlsxToCsv",
        "pdfToHtml",
        "pptxToHtml",
        "docxToPdf",
    }
)


def _operation(operation_id: str) -> Route:
    """A parameterless system route by operationId (imports and converter actions)."""
    return Route.from_table(routes.OPERATIONS, operation_id)


def _import_form(
    method: str | None, content_type: str | None, parent_id: str | None
) -> dict[str, Any]:
    """The optional import form/JSON fields (server defaults: method=site, type='')."""
    form: dict[str, Any] = {}
    if method is not None:
        form["method"] = method
    if content_type is not None:
        form["type"] = content_type
    if parent_id is not None:
        form["parentId"] = parent_id
    return form


async def import_document(
    client: HaxcmsClient,
    kind: str,
    *,
    filename: str,
    content: bytes,
    mimetype: str,
    method: str | None = None,
    content_type: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """POST actions/import-{kind} (multipart) -> `{items, filename, ...}`.

    The document importers read `req.files[0]`, so any file-field name works; we send
    `file-upload` (the Phase 5 convention). Optional form fields: `method`
    (site|branch|page), `type` (course|portfolio; empty falls back to lesson-overview
    content), `parentId`. importDocx enforces the .docx extension AND zip magic;
    importXlsx echoes `selectedSheet`. Errors are 400 with `data.error`.
    """
    route = IMPORT_KIND_ROUTES.get(kind)
    if route is None:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown import kind {kind!r}",
            hint=f"supported kinds: {', '.join(sorted(IMPORT_KIND_ROUTES))}",
        )
    response = await client.call(
        _operation(route),
        files={"file-upload": (filename, content, mimetype)},
        data=_import_form(method, content_type, parent_id) or None,
    )
    return unwrap_dict(response)


async def import_platform(
    client: HaxcmsClient,
    platform: str,
    *,
    repo_url: str | None = None,
    filename: str | None = None,
    content: bytes | None = None,
    mimetype: str | None = None,
    method: str | None = None,
    content_type: str | None = None,
    parent_id: str | None = None,
) -> dict[str, Any]:
    """POST site/import/{platform} -> `{items, filename, files?, siteFiles?, site?}`.

    Two body modes (siteImport.js): a multipart FILE upload — only the `html` platform
    accepts one, with the field name restricted to upload|file|file-upload and the
    extension to .html/.htm — or JSON `{repoUrl, method?, type?, parentId?}` for the
    remote platforms (haxcms, pressbooks, gitbook, notion, wordpress, elmsln,
    drupal, plone, openstax, vitepress, quarto). The dispatcher lowercases/trims the
    platform (unknown -> 400 'Unsupported import platform'). `repoUrl` passes the
    safeFetch SSRF guard: private, loopback and link-local addresses are refused with
    400 `data.error`, and fetch failures are 400 too.
    """
    route = routes.site_import_by_platform(platform.strip().lower())
    form = _import_form(method, content_type, parent_id)
    if content is not None:
        if filename is None:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                "filename is required for a multipart platform import",
            )
        response = await client.call(
            route,
            files={"file-upload": (filename, content, mimetype or "text/html")},
            data=form or None,
        )
    else:
        if not repo_url:
            raise HaxcmsMcpError(
                ErrorCode.INVALID_ARGUMENT,
                "import_platform needs either repo_url or file content",
            )
        payload: dict[str, Any] = {"repoUrl": repo_url, **form}
        response = await client.call(route, json=payload)
    return unwrap_dict(response)


async def action(
    client: HaxcmsClient,
    operation_id: str,
    *,
    json: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    raw: bool = False,
    timeout: float | None = None,
) -> Any:
    """POST one of the twelve converter actions by spec operationId (ADR-0002).

    JSON-body converters (mdToHtml, htmlToMd, prettyHtml, jsonToYaml, yamlToJson) take
    `json`; the multipart converters (docxToHtml, xlsxToCsv, pdfToHtml, pptxToHtml and —
    contra the vendored spec, source-verified — htmlToDocx, htmlToPdf) take `files`;
    xlsxToCsv's sheet rides in `params`. Envelope results come back as `data`
    (`{contents, ...}`; base64 `contents` + `filename` for htmlToDocx/htmlToPdf).
    `raw=True` returns the response BYTES for docxToPdf, which streams application/pdf
    past the envelope. Errors are 400 with `data.error`.
    """
    if operation_id not in ACTION_ROUTES:
        raise HaxcmsMcpError(
            ErrorCode.INVALID_ARGUMENT,
            f"unknown converter operation {operation_id!r}",
            hint=f"supported operations: {', '.join(sorted(ACTION_ROUTES))}",
        )
    response = await client.call(
        _operation(operation_id),
        json=json,
        files=files,
        data=data,
        params=params,
        timeout=timeout,
    )
    if raw:
        if response.status_code >= 400:
            raise error_from_response(response)
        return response.content
    return unwrap(response)


# --- Phase 8: downloads, skeletons, templates (T8.2) ------------------------------------------
# All three POSTs sit on SystemRoutesMap's admin list (bearer + X-HAXCMS-User-Token, the same
# gate clone/archive use). Response shapes source-verified in
# ../haxcms-nodejs/src/systemRoutes/v1/routes/{downloadSite,downloadSiteSkeleton,
# saveSiteAsTemplate}.js; the zips are served from the static, UNAUTHENTICATED _published
# mount (app.js `app.use('/_published/', ...)`).


async def download_site(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """POST sites/{name}/download -> `{link: "/_published/<name>.zip", name: "<name>.zip"}`.

    The server zips the whole site folder (minus node_modules/.git) into the _published
    directory; fetch the bytes with `fetch_published(client, link)`. Zipping runs inside
    the request, so the call gets the export timeout.
    """
    response = await client.call(
        routes.download_site(site),
        json={"site": {"name": site}},
        timeout=client.settings.export_timeout_s,
    )
    return unwrap_dict(response)


async def download_site_skeleton(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """POST sites/{name}/download-skeleton -> `{skeleton, filename: "<machineName>.json"}`.

    The skeleton comes back INLINE — API-REF §3.4 guessed `{link, name}`; the source shows
    `{skeleton, filename}`. Shape: `{meta: {name, machineName, type: "skeleton", ...},
    site: {name, description, theme, settings, platform}, build: {type: "skeleton",
    structure: "from-skeleton", items: [{id, title, slug, order, parent, indent, content,
    metadata}], files: []}, theme, _skeleton}` — items carry their page CONTENT inline.
    """
    response = await client.call(
        routes.download_site_skeleton(site),
        json={"site": {"name": site}},
        timeout=client.settings.export_timeout_s,
    )
    return unwrap_dict(response)


async def save_site_as_template(client: HaxcmsClient, site: str) -> dict[str, Any]:
    """POST sites/{name}/save-as-template -> `{saved, name, filename, path, link}`.

    Writes the generated skeleton to `<configDirectory>/user/skeletons/<machineName>.json`;
    the skeletons list route scans core AND user directories, so the template shows up in
    `list_skeletons` (and `get_skeleton(name)` follows the returned `link`).
    """
    response = await client.call(
        routes.save_site_as_template(site),
        json={"site": {"name": site}},
        timeout=client.settings.export_timeout_s,
    )
    return unwrap_dict(response)


async def fetch_published(client: HaxcmsClient, link: str) -> bytes:
    """GET a `download_site` link off the static _published mount -> the raw zip bytes.

    The mount has NO auth (app.js serves it with res.sendFile), so this is auth="none";
    the export timeout covers large sites on slow disks.
    """
    response = await client.request(
        "GET", link, auth="none", timeout=client.settings.export_timeout_s
    )
    if response.status_code >= 400:
        raise error_from_response(response)
    return response.content
