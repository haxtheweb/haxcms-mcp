"""Vendor the HAXcms NodeJS OpenAPI specs into specs/ (PLAN.md T0.6).

Usage:
    uv run python scripts/sync_specs.py --from ../haxcms-nodejs
    uv run python scripts/sync_specs.py --tag v26.8.1

Copies `system-spec.yaml` and `site-spec.yaml` from the checkout's `src/openapi/`
(or from GitHub raw at a tag) into `specs/` and writes `specs/VERSION`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = REPO_ROOT / "specs"
SPEC_FILES = ("system-spec.yaml", "site-spec.yaml")
RAW_BASE = "https://raw.githubusercontent.com/haxtheweb/haxcms-nodejs"


def _write_version(version: str, commit: str) -> None:
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    (SPECS_DIR / "VERSION").write_text(f"{version} {commit}\n", encoding="utf-8")


def sync_from_checkout(checkout: Path) -> None:
    openapi = checkout / "src" / "openapi"
    if not openapi.is_dir():
        raise SystemExit(f"error: {openapi} not found; is this a haxcms-nodejs checkout?")
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    for name in SPEC_FILES:
        src = openapi / name
        if not src.is_file():
            raise SystemExit(f"error: {src} not found")
        shutil.copyfile(src, SPECS_DIR / name)
        print(f"copied {src} -> {SPECS_DIR / name}")

    pkg = json.loads((checkout / "package.json").read_text(encoding="utf-8"))
    version = pkg.get("version", "unknown")
    try:
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        commit = "unknown"
    _write_version(version, commit)
    print(f"wrote {SPECS_DIR / 'VERSION'}: {version} {commit}")


def sync_from_tag(tag: str) -> None:
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    for name in SPEC_FILES:
        url = f"{RAW_BASE}/{tag}/src/openapi/{name}"
        resp = httpx.get(url, follow_redirects=True, timeout=60)
        if resp.status_code != 200:
            raise SystemExit(f"error: GET {url} -> {resp.status_code}")
        (SPECS_DIR / name).write_bytes(resp.content)
        print(f"downloaded {url} -> {SPECS_DIR / name}")

    pkg_url = f"{RAW_BASE}/{tag}/package.json"
    resp = httpx.get(pkg_url, follow_redirects=True, timeout=60)
    version = "unknown"
    if resp.status_code == 200:
        version = resp.json().get("version", "unknown")
    _write_version(version, tag)
    print(f"wrote {SPECS_DIR / 'VERSION'}: {version} {tag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from", dest="checkout", help="path to a local haxcms-nodejs checkout")
    group.add_argument("--tag", help="git tag/ref to download from GitHub")
    args = parser.parse_args(argv)
    if args.checkout:
        sync_from_checkout(Path(args.checkout).resolve())
    else:
        sync_from_tag(args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
