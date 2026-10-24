"""Spawn real haxcms-mcp subprocesses for the live transport tests (PLAN Phase 9).

Two helpers:

* `stdio_client(env)` — a fastmcp `Client` over `StdioTransport` that spawns
  `python -m haxcms_mcp` and tears the subprocess down when the connection closes
  (keep_alive=False), so `async with stdio_client(...)` is self-cleaning.
* `HttpMcpProcess` — a `subprocess.Popen` wrapper around `--transport http`: waits for
  the TCP port to accept, exposes `.url`, and kills the whole process tree on `stop()`
  (taskkill /T on Windows, killpg on POSIX — the HaxcmsRuntime teardown pattern).

Environment: `server_env()` layers the HAXCMS_MCP_* settings over a copy of os.environ —
the full environment matters on Windows (SystemRoot) and keeps `uv run` PATH entries.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client import StdioTransport

MODULE = "haxcms_mcp"


def free_port() -> int:
    """An OS-assigned TCP port that is free right now (small race, fine for tests)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def server_env(
    base_url: str,
    username: str | None = None,
    password: str | None = None,
    **extra: str,
) -> dict[str, str]:
    """os.environ plus the HAXCMS_MCP_* settings for one spawned server."""
    env = dict(os.environ)
    env["HAXCMS_MCP_BASE_URL"] = base_url
    if username is not None:
        env["HAXCMS_MCP_USERNAME"] = username
    if password is not None:
        env["HAXCMS_MCP_PASSWORD"] = password
    env.update(extra)
    return env


def stdio_client(
    env: dict[str, str],
    *,
    cwd: str | Path | None = None,
    log_file: Path | None = None,
) -> Client:
    """A Client that spawns `python -m haxcms_mcp` on stdio; dies with the connection."""
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", MODULE],
        env=env,
        cwd=str(cwd) if cwd is not None else None,
        keep_alive=False,
        log_file=log_file,
    )
    return Client(transport)


class HttpMcpProcess:
    """`haxcms-mcp --transport http` as a supervised subprocess."""

    def __init__(
        self,
        env: dict[str, str],
        *,
        host: str = "127.0.0.1",
        port: int | None = None,
        path: str = "/mcp",
        log_dir: Path | None = None,
        ready_timeout_s: float = 60.0,
    ) -> None:
        self.env = env
        self.host = host
        self.port = port if port is not None else free_port()
        self.path = path
        self.ready_timeout_s = ready_timeout_s
        self.url = f"http://{host}:{self.port}{path}"
        self.process: subprocess.Popen[bytes] | None = None
        self._log_dir = log_dir
        self._log_files: list[Any] = []

    async def start(self) -> HttpMcpProcess:
        kwargs: dict[str, Any] = {"env": self.env, "stdin": subprocess.DEVNULL}
        if self._log_dir is not None:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            out = open(self._log_dir / "mcp-stdout.log", "wb")  # noqa: SIM115
            err = open(self._log_dir / "mcp-stderr.log", "wb")  # noqa: SIM115
            self._log_files = [out, err]
            kwargs["stdout"] = out
            kwargs["stderr"] = err
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                MODULE,
                "--transport",
                "http",
                "--host",
                self.host,
                "--port",
                str(self.port),
                "--path",
                self.path,
            ],
            **kwargs,
        )
        await self._wait_ready()
        return self

    async def _wait_ready(self) -> None:
        assert self.process is not None
        deadline = time.perf_counter() + self.ready_timeout_s
        while time.perf_counter() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"haxcms-mcp exited with code {self.process.returncode} during boot.\n"
                    f"{self.log_tail()}"
                )
            try:
                with socket.create_connection((self.host, self.port), timeout=1.0):
                    return
            except OSError:
                await asyncio.sleep(0.2)
        raise RuntimeError(
            f"haxcms-mcp HTTP port {self.port} not ready after {self.ready_timeout_s}s.\n"
            f"{self.log_tail()}"
        )

    def log_tail(self, lines: int = 40) -> str:
        chunks: list[str] = []
        if self._log_dir is not None:
            for name in ("mcp-stdout.log", "mcp-stderr.log"):
                path = self._log_dir / name
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                tail = "\n".join(text.splitlines()[-lines:])
                if tail:
                    chunks.append(f"--- {name} ---\n{tail}")
        return "\n".join(chunks)

    async def stop(self) -> None:
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
                    proc.wait(timeout=5)
        self.process = None
        for handle in self._log_files:
            with contextlib.suppress(OSError):
                handle.close()
        self._log_files = []

    async def __aenter__(self) -> HttpMcpProcess:
        return await self.start()

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()
