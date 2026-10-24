"""Install, spawn, and tear down a real HAXcms NodeJS instance for tests.

Implements PLAN.md Section 6.2 and API-REF Section 11 (steps 1-5) exactly. Works on Windows,
macOS, and Linux. The npm package is installed once into `.haxcms-runtime/` (gitignored) unless
`HAXCMS_MCP_TEST_HAXCMS_DIR` points at a local `haxcms-nodejs` checkout.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_CACHE = REPO_ROOT / ".haxcms-runtime"

# Files copied from boilerplate/systemsetup into _config/ (API-REF §11 step 2)
BOILERPLATE_FILES = (
    "config.json",
    "my-custom-elements.js",
    "userData.json",
    "config.php",
    ".htaccess",
    ".user-files-htaccess",
)
# Directories created under _config/ (API-REF §11 step 2)
CONFIG_SUBDIRS = (
    "tmp",
    "cache",
    "user/files",
    "user/skeletons",
    "skeletons",
    "settings",
    "node_modules",
)

INSTALL_SECONDS: float | None = None  # recorded by the first ensure_haxcms() that installs


def _npm() -> str:
    found = shutil.which("npm.cmd" if sys.platform == "win32" else "npm") or shutil.which("npm")
    if not found:
        raise RuntimeError("npm not found on PATH (required by the test harness)")
    return found


def _node() -> str:
    found = shutil.which("node")
    if not found:
        raise RuntimeError("node not found on PATH (required by the test harness)")
    return found


def _test_haxcms_dir() -> Path | None:
    value = os.environ.get("HAXCMS_MCP_TEST_HAXCMS_DIR")
    if value:
        return Path(value).resolve()
    # The npm-published @haxtheweb/haxcms-nodejs@26.8.1 dist is OLDER than the API this
    # project targets: specs/VERSION pins "26.8.1 e969655c" and specs/site-spec.yaml (the
    # source of truth) documents the files.json datastore, width/height on file records and
    # the compress + duplicate operations that PLAN Phase 5 requires — none of which the
    # published dist has (verified by reading both builds). When the optional sibling
    # checkout (PLAN §0.4) is present, prefer it so the live runtime matches the committed
    # spec; ensure_haxcms() npm-installs its dependencies (node_modules only, no source
    # edits). Falls back to the npm dist when there is no sibling (e.g. CI). This deviation
    # from the npm-dist default, and the user's approval to install into the sibling
    # checkout, are recorded in PROGRESS.md under Phase 5.
    sibling = REPO_ROOT.parent / "haxcms-nodejs"
    if (sibling / "src" / "app.js").is_file():
        return sibling.resolve()
    return None


def _test_version() -> str:
    return os.environ.get("HAXCMS_MCP_TEST_HAXCMS_VERSION", "26.8.1")


def ensure_haxcms() -> Path:
    """Return the path to the HAXcms `app.js` entry point, installing the package if needed."""
    global INSTALL_SECONDS
    checkout = _test_haxcms_dir()
    if checkout is not None:
        app_js = checkout / "src" / "app.js"
        if not app_js.is_file():
            raise RuntimeError(f"{app_js} not found; bad HAXCMS_MCP_TEST_HAXCMS_DIR?")
        if not (checkout / "node_modules").is_dir():
            started = time.perf_counter()
            subprocess.run([_npm(), "install"], cwd=checkout, check=True)
            INSTALL_SECONDS = time.perf_counter() - started
        return app_js

    package = RUNTIME_CACHE / "node_modules" / "@haxtheweb" / "haxcms-nodejs"
    app_js = package / "dist" / "app.js"
    if not app_js.is_file():
        RUNTIME_CACHE.mkdir(exist_ok=True)
        started = time.perf_counter()
        subprocess.run(
            [
                _npm(),
                "install",
                "--prefix",
                str(RUNTIME_CACHE),
                f"@haxtheweb/haxcms-nodejs@{_test_version()}",
            ],
            cwd=str(RUNTIME_CACHE),
            check=True,
        )
        INSTALL_SECONDS = time.perf_counter() - started
        print(
            f"[harness] npm install of @haxtheweb/haxcms-nodejs@{_test_version()} "
            f"took {INSTALL_SECONDS:.1f}s",
            file=sys.stderr,
        )
    if not app_js.is_file():
        raise RuntimeError(f"npm install succeeded but {app_js} is missing")
    return app_js


def boilerplate_dir(app_js: Path) -> Path:
    """boilerplate/systemsetup lives next to app.js in both npm and checkout layouts."""
    return app_js.parent / "boilerplate" / "systemsetup"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class HaxcmsRuntime:
    """Async context manager that boots an isolated HAXcms NodeJS instance (API-REF §11)."""

    username: str = "mcpuser"
    password: str = field(default_factory=lambda: secrets.token_hex(16))
    keep: bool | None = None  # default: HAXCMS_MCP_TEST_KEEP_RUNTIME
    ready_timeout_s: float = 60.0

    app_js: Path | None = field(default=None, init=False)
    runtime_root: Path | None = field(default=None, init=False)
    base_url: str = field(default="", init=False)
    process: subprocess.Popen[bytes] | None = field(default=None, init=False)
    boot_seconds: float = field(default=0.0, init=False)
    _log_files: list[Any] = field(default_factory=list, init=False)
    _home_dir: Path | None = field(default=None, init=False)

    def _keep_runtime(self) -> bool:
        if self.keep is not None:
            return self.keep
        return os.environ.get("HAXCMS_MCP_TEST_KEEP_RUNTIME", "").lower() in {"1", "true", "yes"}

    async def __aenter__(self) -> HaxcmsRuntime:
        self.app_js = ensure_haxcms()
        started = time.perf_counter()

        # --- §11 step 1: runtime skeleton -----------------------------------
        root = Path(tempfile.mkdtemp(prefix="haxcms-mcp-rt-"))
        (root / "_sites").mkdir()
        config = root / "_config"
        config.mkdir()
        (config / ".isHAXcmsConfig").write_text("", encoding="utf-8")

        # --- §11 step 2: boilerplate + config subdirs -------------------------
        boilerplate = boilerplate_dir(self.app_js)
        if not boilerplate.is_dir():
            raise RuntimeError(f"boilerplate dir {boilerplate} not found")
        for name in BOILERPLATE_FILES:
            src = boilerplate / name
            if src.is_file():
                shutil.copy2(src, config / name)
        for sub in CONFIG_SUBDIRS:
            (config / sub).mkdir(parents=True, exist_ok=True)

        # --- §11 step 3: login user -------------------------------------------
        (config / ".user").write_text(
            json.dumps({"name": self.username, "password": self.password}), encoding="utf-8"
        )

        # --- §11 step 4: environment -------------------------------------------
        port = _free_port()
        home = Path(tempfile.mkdtemp(prefix="haxcms-mcp-home-"))
        self._home_dir = home
        env = dict(os.environ)
        env["HAXCMS_ROOT"] = str(root) + os.sep  # trailing slash required
        env["PORT"] = str(port)
        env["HOME"] = str(home)
        if sys.platform == "win32":
            env["USERPROFILE"] = str(home)
        env["GIT_AUTHOR_NAME"] = "HAXcms MCP Tests"
        env["GIT_AUTHOR_EMAIL"] = "tests@example.invalid"
        env["GIT_COMMITTER_NAME"] = "HAXcms MCP Tests"
        env["GIT_COMMITTER_EMAIL"] = "tests@example.invalid"
        env.pop("NODE_ENV", None)
        env.pop("HAXCMS_DISABLE_JWT_CHECKS", None)

        # --- §11 step 5: spawn node dist/app.js --------------------------------
        stdout_f = open(root / "haxcms-stdout.log", "wb")  # noqa: SIM115
        stderr_f = open(root / "haxcms-stderr.log", "wb")  # noqa: SIM115
        self._log_files = [stdout_f, stderr_f]
        popen_kwargs: dict[str, Any] = {
            "cwd": str(root),
            "env": env,
            "stdout": stdout_f,
            "stderr": stderr_f,
            "stdin": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True
        self.process = subprocess.Popen([_node(), str(self.app_js)], **popen_kwargs)
        self.runtime_root = root
        self.base_url = f"http://127.0.0.1:{port}"

        await self._wait_ready()
        self.boot_seconds = time.perf_counter() - started
        print(
            f"[harness] HAXcms booted at {self.base_url} in {self.boot_seconds:.1f}s (root={root})",
            file=sys.stderr,
        )
        return self

    async def _wait_ready(self) -> None:
        assert self.process is not None
        deadline = time.perf_counter() + self.ready_timeout_s
        status_url = f"{self.base_url}/system/api/v1/status"
        last_error = ""
        while time.perf_counter() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"HAXcms exited with code {self.process.returncode} during boot.\n"
                    f"{self._log_tail()}"
                )
            try:
                httpx.get(status_url, timeout=2.0)
                return  # any HTTP status counts as ready (§11 step 5)
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise RuntimeError(
            f"HAXcms not ready after {self.ready_timeout_s}s (last error: {last_error}).\n"
            f"{self._log_tail()}"
        )

    def _log_tail(self, lines: int = 40) -> str:
        assert self.runtime_root is not None
        chunks = []
        for name in ("haxcms-stdout.log", "haxcms-stderr.log"):
            path = self.runtime_root / name
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            tail = "\n".join(text.splitlines()[-lines:])
            if tail:
                chunks.append(f"--- {name} ---\n{tail}")
        return "\n".join(chunks)

    async def __aexit__(self, *exc_info: object) -> None:
        proc = self.process
        if proc is not None and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if sys.platform != "win32":
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=10)
        for handle in self._log_files:
            with contextlib.suppress(OSError):
                handle.close()
        if not self._keep_runtime():
            if self.runtime_root is not None:
                shutil.rmtree(self.runtime_root, ignore_errors=True)
            if self._home_dir is not None:
                shutil.rmtree(self._home_dir, ignore_errors=True)

    # --- disk inspection helpers ------------------------------------------------
    def site_dir(self, site: str) -> Path:
        assert self.runtime_root is not None
        return self.runtime_root / "_sites" / site

    def read_site_json(self, site: str) -> dict[str, Any]:
        path = self.site_dir(site) / "site.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def read_page_html(self, site: str, item_id: str) -> str:
        path = self.site_dir(site) / "pages" / item_id / "index.html"
        return path.read_text(encoding="utf-8")
