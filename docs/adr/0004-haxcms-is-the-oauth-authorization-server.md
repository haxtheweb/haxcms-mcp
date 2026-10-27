# HAXcms is the OAuth authorization server; the MCP server is only a resource server

Status: **proposed**. Needs sign-off from HAXcms core ([haxtheweb/issues#3140](https://github.com/haxtheweb/issues/issues/3140)) because most of option A lands in haxcms-nodejs and haxcms-php.

Over stdio the server acts as one HAXcms account (environment credentials or the `login` tool), and that stays. A hosted connector that anyone can add needs each person to act as themselves, with their own HAXcms permissions. MCP's authorization model is OAuth 2.1: the MCP server is a protected resource that advertises its authorization server (RFC 9728), and clients use authorization code + PKCE.

We chose **option A: HAXcms is the authorization server**. The MCP server verifies the bearer a client presents by asking HAXcms (`GET /system/api/v1/session` with that bearer). It then calls HAXcms *with that same token*, so HAXcms keeps every authorization decision: which sites a user may touch (including HAXiam's per-user site directories), the `mcp.enabled` / `mcp.readOnly` policy, and the deployment profile. Nothing about users is stored or mapped here.

We rejected **option B (an external IdP mapped onto HAXcms users)**. It would put a second identity store in this server, plus a mapping table and a token exchange. HAXcms would then see every call as one privileged service account, so the MCP server would have to re-implement HAXcms's per-site authorization. Getting that wrong is a privilege-escalation bug, and the logic would drift from HAXcms over time.

## What this server does now (this ADR's PR)

- `HAXCMS_MCP_HTTP_AUTH=haxcms` turns on per-caller auth for `--transport http`:
  - Requests without a valid HAXcms bearer get `401` with `WWW-Authenticate: Bearer resource_metadata=...` before any tool runs.
  - `/.well-known/oauth-protected-resource/<path>` names the HAXcms instance (or `HAXCMS_MCP_AUTHORIZATION_SERVER_URL`) as the authorization server.
- Each caller gets a session keyed by a hash of their token: its own cookie jar, User Token and Site Token cache.
  - The User Token and Site Tokens are fetched from `session/connection-settings` with the caller's bearer.
  - Environment credentials are never used in this mode.
  - `login` and `logout` answer `UNSUPPORTED`.
  - A refused token is `AUTH_FAILED` ("re-authorize the connector"), never a silent re-login.
- Fail closed: `--transport http` on anything but a loopback host refuses to start unless `HAXCMS_MCP_HTTP_AUTH` is set.
- In HTTP mode, URL sources go through an SSRF guard:
  - http/https only, no credentials in the URL.
  - Every resolved address must be public: no loopback, RFC 1918, link-local / cloud metadata, CGNAT, multicast, reserved, or IPv6 forms that embed one of those.
  - Connections are pinned to the validated IP (Host header and SNI keep the name).
  - Redirects are followed manually and each hop is re-validated, at most 5.
  - The body streams against the 50 MB cap.
- Local-path sources are refused in HTTP mode, because the path would be read from the *server's* disk. Operators can override both rules (`HAXCMS_MCP_ALLOW_PRIVATE_URL_SOURCES`, `HAXCMS_MCP_ALLOW_LOCAL_SOURCES`) on a trusted network.
- Read-Only Mode still applies to every caller.

Until HAXcms has OAuth endpoints, a client that can send a static header can connect with a HAXcms access token (`Authorization: Bearer <jwt>`). That path is for testing only, since HAXcms tokens live 15 minutes.

## What HAXcms needs (upstream, both backends)

1. Authorization server metadata at `/.well-known/oauth-authorization-server` (RFC 8414).
2. `authorize` endpoint: the existing login plus a consent screen; authorization code + PKCE (S256 only).
3. `token` endpoint: issues access tokens and rotating refresh tokens. Access tokens must be accepted by the HAXcms APIs exactly like today's JWTs.
4. Client registration: dynamic client registration (RFC 7591), or client ID metadata documents, so a connector can be added without an admin.
5. Audience binding (RFC 8707 `resource`): tokens minted for an MCP server carry `aud` = that server's resource URL.
   - HAXcms should only accept such a token when it arrives via that MCP server. The MCP server then forwards a token that was issued for HAXcms through it, which is not general token passthrough.
   - Until then, this server accepts any valid HAXcms token. The README says so.
6. Gate it all behind the existing `mcp.enabled` config, and honour `mcp.readOnly` on tokens.

## Consequences

- Most of the remaining work is in HAXcms. Once HAXcms serves the metadata and the endpoints above, nothing here changes: the protected-resource metadata already points at it.
- The verifier asks HAXcms on every new token and caches the answer for 30 s (refusals for 10 s). A revoked token can keep working for up to 30 s. Verification has its own outbound budget, and an address that keeps presenting refused tokens is throttled, so unauthenticated traffic cannot starve verified callers.
- Verified callers still share one outbound budget for tool calls. Per-caller budgets are a follow-up if one user can starve others in practice.
- Exports and converter files go to a per-user folder with a quota and expiry, and come back as signed, short-lived download links served by this server (security audit, October 2026).
- Server-level MCP administration for HAXiam-hosted sites is out of scope and not advertised. This is for self-hosted HAXcms.
