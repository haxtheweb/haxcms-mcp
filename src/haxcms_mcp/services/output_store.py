"""Where exports and converter results are written, per transport (security audit).

Over stdio the Output Directory is the operator's own folder: results land in
`OUTPUT_DIR[/<sub>]/<name>` and tools report the absolute path, as before.

With per-caller auth (`HAXCMS_MCP_HTTP_AUTH=haxcms`) the server's disk is shared by remote
callers who cannot read it, so:

* each caller writes under `OUTPUT_DIR/callers/<hash of their token's user>/...` — never into
  another caller's folder;
* files older than `OUTPUT_TTL_S` are pruned on every write, and a write that would take the
  caller over `OUTPUT_CALLER_QUOTA_MB` is refused (`QUOTA_EXCEEDED`-style RATE_LIMITED);
* the tool result carries a short-lived, signed `download_url` served by this server
  (`GET /downloads/<token>`) and a path relative to the Output Directory, never the server's
  absolute filesystem layout.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from haxcms_mcp.client.principal import current_principal
from haxcms_mcp.config import Settings
from haxcms_mcp.errors import ErrorCode, HaxcmsMcpError

DOWNLOAD_PREFIX = "/downloads/"
CALLERS_DIR = "callers"
MAX_UNIQUE_SUFFIX = 1000

# Signs download tokens. Per process: links die with the process, which is the intent.
_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True)
class StoredFile:
    path: Path  # absolute, on this server
    reported_path: str  # what the tool result shows
    download_url: str | None
    expires_at: float | None


def caller_key() -> str | None:
    """Stable per-USER folder name in per-caller mode (tokens rotate; users do not)."""
    principal = current_principal.get()
    if principal is None:
        return None
    identity = principal.username or principal.key
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def output_root(settings: Settings) -> Path:
    """The folder this request may write into (the caller's own in per-caller mode)."""
    if not settings.per_caller_auth:
        return settings.output_dir
    key = caller_key()
    if key is None:
        raise HaxcmsMcpError(
            ErrorCode.AUTH_REQUIRED,
            "writing results needs an authenticated caller",
        )
    return settings.output_dir / CALLERS_DIR / key


def _unique_path(directory: Path, filename: str) -> Path:
    """The first free `<stem>-<n><suffix>` slot, so results never overwrite each other."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    for index in range(1, MAX_UNIQUE_SUFFIX):
        candidate = directory / f"{path.stem}-{index}{path.suffix}"
        if not candidate.exists():
            return candidate
    raise HaxcmsMcpError(
        ErrorCode.UPSTREAM_ERROR,
        f"no free filename for {filename!r}",
        hint="the output directory holds too many same-named results; clear it",
    )


def _files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]


def _prune_and_check_quota(settings: Settings, root: Path, incoming: int) -> None:
    now = time.time()
    used = 0
    for path in _files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        if now - stat.st_mtime > settings.output_ttl_s:
            path.unlink(missing_ok=True)
        else:
            used += stat.st_size
    quota = settings.output_caller_quota_mb * 1024 * 1024
    if used + incoming > quota:
        raise HaxcmsMcpError(
            ErrorCode.RATE_LIMITED,
            f"this result ({incoming} bytes) would exceed your {settings.output_caller_quota_mb}"
            f"mb output quota on this server ({used} bytes in use)",
            hint="download earlier results first; files expire after "
            f"{settings.output_ttl_s // 60} minutes",
        )


def sign_download(settings: Settings, path: Path, expires_at: float) -> str:
    relative = path.relative_to(settings.output_dir).as_posix()
    payload = f"{relative}\n{int(expires_at)}".encode()
    mac = hmac.new(_SECRET, payload, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(payload + b"\n" + mac).decode("ascii").rstrip("=")


def resolve_download(settings: Settings, token: str, *, now: float | None = None) -> Path | None:
    """The file a download token names, if the signature holds and it has not expired."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        relative, expires, mac = raw.split(b"\n", 2)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(_SECRET, relative + b"\n" + expires, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        if (now if now is not None else time.time()) > int(expires):
            return None
        root = settings.output_dir.resolve()
        path = (settings.output_dir / relative.decode("utf-8")).resolve()
    except (ValueError, UnicodeDecodeError, OSError):
        return None
    if root not in path.parents or not path.is_file():
        return None
    return path


def download_base(settings: Settings) -> str:
    base = settings.public_url or f"http://{settings.http_host}:{settings.http_port}"
    return base.rstrip("/") + DOWNLOAD_PREFIX


def store(raw: bytes, *, settings: Settings, filename: str, sub: str | None = None) -> StoredFile:
    """Write one result under the right root and describe it for the tool result."""
    root = output_root(settings)
    if settings.per_caller_auth:
        _prune_and_check_quota(settings, root, len(raw))
    directory = root / sub if sub else root
    path = _unique_path(directory, filename)
    path.write_bytes(raw)
    if not settings.per_caller_auth:
        return StoredFile(path, str(path), None, None)
    expires_at = time.time() + settings.download_ttl_s
    token = sign_download(settings, path, expires_at)
    return StoredFile(
        path,
        path.relative_to(settings.output_dir).as_posix(),
        download_base(settings) + token,
        expires_at,
    )
