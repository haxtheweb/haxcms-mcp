"""Install, spawn, and tear down a real HAXcms PHP instance for tests (#3139).

Select it with `HAXCMS_MCP_TEST_BACKEND=php` and point `HAXCMS_MCP_TEST_HAXCMS_PHP_DIR` at a
`haxtheweb/haxcms-php` checkout. Like the NodeJS runtime there is no implicit sibling lookup.

HAXcms PHP is normally served by Apache (see its Dockerfile). The harness instead runs PHP's
built-in web server (`php -S`) with `php_router.php` standing in for the .htaccess rewrites, so
the suite needs only the `php` binary (8.3, gd/curl/mbstring/dom/zip) and no Docker or Apache.
The instance is installed through its own `install.php` using the hosting-provider direct
install path (`_installtoken.txt` + `install_token`), so the real installer code builds
`_config/` exactly as in production.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from tests.harness.haxcms_runtime import HaxcmsRuntime, _free_port

ROUTER = Path(__file__).resolve().parent / "php_router.php"

# What the runtime needs from a checkout; the rest (front-end build, node_modules, e2e tests,
# git history) is large and irrelevant to the HTTP API.
_IGNORE = shutil.ignore_patterns(
    ".git",
    "build",
    "node_modules",
    "test",
    "tests",
    "archived",
    "published",
)


def _policy_password() -> str:
    """HAXcms PHP enforces 8+ chars with upper, lower, digit and symbol on install."""
    return f"Mcp{secrets.token_hex(8)}!9"


def php_checkout_dir() -> Path:
    value = os.environ.get("HAXCMS_MCP_TEST_HAXCMS_PHP_DIR")
    if not value:
        raise RuntimeError(
            "HAXCMS_MCP_TEST_BACKEND=php needs HAXCMS_MCP_TEST_HAXCMS_PHP_DIR to point at a "
            "haxtheweb/haxcms-php checkout (git clone https://github.com/haxtheweb/haxcms-php)"
        )
    path = Path(value).resolve()
    if not (path / "install.php").is_file():
        raise RuntimeError(f"{path} is not a haxcms-php checkout (no install.php)")
    return path


def _php() -> str:
    found = shutil.which("php")
    if not found:
        raise RuntimeError("php not found on PATH (required by HAXCMS_MCP_TEST_BACKEND=php)")
    return found


@dataclass
class HaxcmsPhpRuntime(HaxcmsRuntime):
    """A real HAXcms PHP instance with the same surface as `HaxcmsRuntime`."""

    password: str = field(default_factory=_policy_password)
    workers: int = 4  # PHP_CLI_SERVER_WORKERS: the CLI server is single-threaded otherwise
    backend: str = field(default="php", init=False)

    async def __aenter__(self) -> HaxcmsPhpRuntime:
        checkout = php_checkout_dir()
        self.app_js = checkout / "install.php"  # kept for parity with the NodeJS runtime
        started = time.perf_counter()

        root = Path(tempfile.mkdtemp(prefix="haxcms-mcp-php-rt-"))
        shutil.copytree(checkout, root, ignore=_IGNORE, symlinks=True, dirs_exist_ok=True)
        # runtime state lives beside the code; the installer creates _config/ and friends
        for sub in ("_sites", "_published", "_archived"):
            (root / sub).mkdir(exist_ok=True)
        install_token = secrets.token_hex(16)
        (root / "_installtoken.txt").write_text(install_token, encoding="utf-8")

        port = _free_port()
        home = Path(tempfile.mkdtemp(prefix="haxcms-mcp-home-"))
        self._home_dir = home
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["PHP_CLI_SERVER_WORKERS"] = str(self.workers)
        env["GIT_AUTHOR_NAME"] = "HAXcms MCP Tests"
        env["GIT_AUTHOR_EMAIL"] = "tests@example.invalid"
        env["GIT_COMMITTER_NAME"] = "HAXcms MCP Tests"
        env["GIT_COMMITTER_EMAIL"] = "tests@example.invalid"

        stdout_f = open(root / "haxcms-stdout.log", "wb")  # noqa: SIM115
        stderr_f = open(root / "haxcms-stderr.log", "wb")  # noqa: SIM115
        self._log_files = [stdout_f, stderr_f]
        command = [
            _php(),
            "-d",
            "display_errors=0",
            "-d",
            "log_errors=1",
            "-d",
            "error_reporting=E_ALL & ~E_NOTICE & ~E_DEPRECATED",
            "-d",
            "memory_limit=512M",
            "-d",
            "upload_max_filesize=64M",
            "-d",
            "post_max_size=64M",
            "-S",
            f"127.0.0.1:{port}",
            "-t",
            str(root),
            str(ROUTER),
        ]
        popen_kwargs: dict[str, object] = {
            "cwd": str(root),
            "env": env,
            "stdout": stdout_f,
            "stderr": stderr_f,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            popen_kwargs["start_new_session"] = True
        self.process = subprocess.Popen(command, **popen_kwargs)  # type: ignore[call-overload]
        self.runtime_root = root
        self.base_url = f"http://127.0.0.1:{port}"

        await self._wait_ready()
        self._install(install_token)
        self.boot_seconds = time.perf_counter() - started
        print(
            f"[harness] HAXcms PHP booted at {self.base_url} in {self.boot_seconds:.1f}s "
            f"(root={root})",
            file=sys.stderr,
        )
        return self

    async def _wait_ready(self) -> None:
        assert self.process is not None
        deadline = time.perf_counter() + self.ready_timeout_s
        url = f"{self.base_url}/install.php?op=state"
        last_error = ""
        while time.perf_counter() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"php -S exited with code {self.process.returncode} during boot.\n"
                    f"{self._log_tail()}"
                )
            try:
                if httpx.get(url, timeout=5.0).status_code == 200:
                    return
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(0.2)
        raise RuntimeError(
            f"HAXcms PHP not ready after {self.ready_timeout_s}s (last error: {last_error}).\n"
            f"{self._log_tail()}"
        )

    def _install(self, install_token: str) -> None:
        """Drive the real installer: prepare runtime dirs, then the token-gated direct install."""
        base = f"{self.base_url}/install.php"
        with httpx.Client(timeout=120.0) as http:
            prepare = http.post(f"{base}?op=prepare")
            if prepare.status_code != 200:
                raise RuntimeError(
                    f"installer prepare failed: {prepare.status_code} {prepare.text}"
                )
            for step in (1, 2, 3):
                http.post(f"{base}?op=advance", json={"toStep": step, "language": "en"})
            done = http.post(
                f"{base}?op=advance",
                json={
                    "toStep": 4,
                    "language": "en",
                    "user": self.username,
                    "pass": self.password,
                    "install_token": install_token,
                },
            )
            body = (
                done.json()
                if done.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if done.status_code != 200 or body.get("hasErrors") or body.get("step") != 4:
                raise RuntimeError(f"installer step 4 failed: {done.status_code} {done.text[:500]}")
