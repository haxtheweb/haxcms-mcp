"""SSRF guard for URL File Sources (#3140).

When the server is reachable by other people (the streamable-HTTP transport), a URL source is
a request the *server* makes on a remote caller's behalf. Without a guard that is a path to
loopback services, the cloud metadata endpoint, and anything else on the server's private
network. `guarded_fetch` therefore:

* accepts only http/https on the default or an explicit port,
* resolves the host itself and refuses unless EVERY address is publicly routable (so a name
  that resolves to both a public and a private address is refused),
* connects to the address it validated (DNS pinning: the URL host is swapped for the IP, the
  original name goes in `Host` and, for https, in SNI / certificate verification), so a
  rebinding DNS answer between check and connect cannot redirect the request,
* follows redirects itself, re-validating every hop, up to `MAX_REDIRECTS`,
* streams the body and stops at the caller's byte cap.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError
from haxcms_mcp.logging import get_logger

logger = get_logger(__name__)

MAX_REDIRECTS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

# IPv6 prefixes that embed an IPv4 address the packet may end up at
_NAT64 = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.IPv6Network("64:ff9b:1::/48")
_SIXTO4 = ipaddress.IPv6Network("2002::/16")

Resolver = Callable[[str, int], Awaitable[list[str]]]

# Never reachable, even when private addresses are allowed (stdio / trusted networks):
# link-local covers the cloud metadata endpoints (169.254.169.254, fd00:ec2::254 aside);
# the rest are well-known metadata addresses outside link-local.
_METADATA_HOSTS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure/OpenStack/DO
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
        ipaddress.ip_address("168.63.129.16"),  # Azure wire server
    }
)


def is_allowed_private_address(address: IPAddress) -> bool:
    """For `allow_private`: loopback / RFC 1918 / ULA / CGNAT are fine, but never link-local,
    metadata endpoints, multicast, reserved or unspecified addresses (or IPv6 forms that
    embed one of those)."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id:
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None and not (
            is_public_address(embedded) or is_allowed_private_address(embedded)
        ):
            return False
    if address in _METADATA_HOSTS:
        return False
    if address.is_loopback:  # ::1 sits inside the reserved ::/8 block
        return True
    return not (
        address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _refused(message: str) -> HaxcmsMcpError:
    return HaxcmsMcpError(
        ErrorCode.FILE_SOURCE_ERROR,
        message,
        hint=(
            "URL sources may only point at public internet addresses (on a trusted network the "
            "operator can allow private ones with HAXCMS_MCP_ALLOW_PRIVATE_URL_SOURCES=true; "
            "link-local and cloud-metadata addresses are never allowed); upload the file "
            "another way (base64:<name>:<payload> or a data: URL)"
        ),
    )


def _embedded_ipv4(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address in _NAT64 or address in _NAT64_LOCAL:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    return None


def is_public_address(address: IPAddress) -> bool:
    """True only for globally routable unicast addresses (no loopback, private, link-local,
    CGNAT, multicast, reserved, unspecified, or IPv6 forms that embed one of those)."""
    if isinstance(address, ipaddress.IPv6Address):
        if address.scope_id:
            return False
        embedded = _embedded_ipv4(address)
        if embedded is not None and not is_public_address(embedded):
            return False
    return bool(
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
    )


async def _system_resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


@dataclass(frozen=True)
class _Target:
    url: str  # what we connect to (host replaced by the validated IP)
    host: str  # original host name, for Host / SNI
    host_header: str


async def validate_url(
    url: str,
    *,
    resolve: Resolver | None = None,
    allow_private: bool = False,
    via_proxy: bool = False,
) -> _Target:
    """Check one URL and pin it to a validated public address (raises FILE_SOURCE_ERROR).

    `via_proxy`: the operator routes URL sources through an egress proxy, which then does
    DNS and enforces where requests may go. Only IP-literal hosts can be checked here; a
    host name is passed to the proxy as-is (no pinning)."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise _refused(f"refusing to fetch {url!r}: only http and https URLs are allowed")
    if parts.username or parts.password:
        raise _refused(f"refusing to fetch {url!r}: URLs with credentials are not allowed")
    host = parts.hostname
    if not host:
        raise _refused(f"refusing to fetch {url!r}: the URL has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise _refused(f"refusing to fetch {url!r}: invalid port") from exc

    try:
        literal: IPAddress | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        candidates = [str(literal)]
    elif via_proxy:
        return _Target(url, host, parts.netloc)
    else:
        resolver = resolve or _system_resolve
        try:
            candidates = list(await resolver(host, port))
        except (OSError, UnicodeError) as exc:
            raise _refused(f"could not resolve {host!r}: {exc}") from exc
    if not candidates:
        raise _refused(f"could not resolve {host!r}")

    addresses: list[IPAddress] = []
    for candidate in candidates:
        try:
            addresses.append(ipaddress.ip_address(candidate.split("%", 1)[0]))
        except ValueError as exc:
            raise _refused(f"{host!r} resolved to an unparseable address {candidate!r}") from exc
        if "%" in candidate:  # scoped (link-local) IPv6
            logger.warning("url source %s resolved to scoped address %s", host, candidate)
            raise _refused(f"refusing to fetch {url!r}: {host!r} resolves to a non-public address")
    allowed = (
        (lambda a: is_public_address(a) or is_allowed_private_address(a))
        if allow_private
        else is_public_address
    )
    blocked = [str(a) for a in addresses if not allowed(a)]
    if blocked:
        # the resolved addresses describe the server's network: log them, never return them
        logger.warning("url source %s resolved to non-public %s", host, ", ".join(blocked))
        raise _refused(f"refusing to fetch {url!r}: {host!r} resolves to a non-public address")

    pinned = addresses[0]
    netloc_host = f"[{pinned}]" if pinned.version == 6 else str(pinned)
    netloc = f"{netloc_host}:{parts.port}" if parts.port else netloc_host
    pinned_url = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    host_header = host if default_port else f"{host}:{port}"
    if ":" in host and not host.startswith("["):  # IPv6 literal in Host
        host_header = f"[{host}]" if default_port else f"[{host}]:{port}"
    return _Target(pinned_url, host, host_header)


@dataclass
class FetchResult:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str  # final logical URL (after redirects)


# Whole-fetch limits (security audit): httpx timeouts are per read, so a server trickling a
# byte a minute could hold a fetch open forever; and every fetch buffers up to the upload cap.
TOTAL_DEADLINE_S = 120.0
MAX_CONCURRENT_FETCHES = 4
_slots: dict[int, asyncio.Semaphore] = {}


def _fetch_slots() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    slots = _slots.get(loop_id)
    if slots is None:
        _slots.clear()  # one live event loop per process; drop semaphores of closed loops
        slots = _slots[loop_id] = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)
    return slots


async def guarded_fetch(
    url: str,
    *,
    timeout_s: float,
    check_size: Callable[[int], None],
    resolve: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    deadline_s: float | None = None,
    allow_private: bool = False,
    proxy: str | None = None,
) -> FetchResult:
    """GET `url` with the SSRF rules above. `check_size(n)` raises when n bytes is too many;
    it is called with the declared Content-Length and again as the body streams in. The whole
    fetch (redirects included) must finish within `deadline_s`, and at most
    MAX_CONCURRENT_FETCHES run at once."""
    limit = TOTAL_DEADLINE_S if deadline_s is None else deadline_s
    async with _fetch_slots():
        try:
            async with asyncio.timeout(limit):
                return await _guarded_fetch(
                    url, timeout_s, check_size, resolve, transport, allow_private, proxy
                )
        except TimeoutError as exc:
            raise _refused(f"fetching {url!r} took longer than {int(limit)}s") from exc


async def _guarded_fetch(
    url: str,
    timeout_s: float,
    check_size: Callable[[int], None],
    resolve: Resolver | None,
    transport: httpx.AsyncBaseTransport | None,
    allow_private: bool,
    proxy: str | None,
) -> FetchResult:
    current = url
    async with httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=False,
        trust_env=False,  # never an implicit proxy: only the operator's explicit one
        transport=transport,
        proxy=proxy if transport is None else None,
    ) as fetcher:
        for _hop in range(MAX_REDIRECTS + 1):
            target = await validate_url(
                current, resolve=resolve, allow_private=allow_private, via_proxy=proxy is not None
            )
            pinned = target.url != current
            extensions = (
                {"sni_hostname": target.host}
                if pinned and current.lower().startswith("https")
                else {}
            )
            request = fetcher.build_request(
                "GET",
                target.url,
                headers={"Host": target.host_header} if pinned else None,
                extensions=extensions,
            )
            response = await fetcher.send(request, stream=True)
            try:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise _refused(f"{current} redirected without a Location header")
                    current = urljoin(current, location)
                    continue
                declared = response.headers.get("content-length")
                if declared and declared.isdigit():
                    check_size(int(declared))
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    check_size(size)
                    chunks.append(chunk)
                return FetchResult(
                    response.status_code, response.headers, b"".join(chunks), current
                )
            finally:
                await response.aclose()
    raise _refused(f"refusing to fetch {url!r}: more than {MAX_REDIRECTS} redirects")
