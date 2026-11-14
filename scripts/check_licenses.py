#!/usr/bin/env python
"""Check that every installed dependency's license can ship with an Apache-2.0 project.

    uv sync && uv run python scripts/check_licenses.py

Licenses are read from each installed distribution's own metadata: the SPDX
`License-Expression` when it has one, otherwise its `License ::` classifiers, otherwise the
free-text `License` field. A dependency passes when every license it names is permissive.
Anything else fails the run: copyleft (GPL, AGPL), weak copyleft that a maintainer must
decide on (LGPL, MPL), and packages that state no license at all.

A package a maintainer has reviewed and accepted is listed in
`.github/license-review.json` as {"name", "license", "reason"}. The entry only matches while
the package still reports that exact license string, so a license change is seen again.

The project itself must declare Apache-2.0 in pyproject.toml and carry the Apache LICENSE.
"""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_FILE = ROOT / ".github" / "license-review.json"
PROJECT = "haxcms-mcp"

# SPDX ids, and the classifier / free-text spellings that mean the same license
PERMISSIVE = {
    "0bsd",
    "apache-2.0",
    "apache 2.0",
    "apache license 2.0",
    "apache software license",
    "bsd",
    "bsd license",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "isc",
    "isc license",
    "isc license (iscl)",
    "mit",
    "mit license",
    "mit-0",
    "mit-cmu",
    "psf-2.0",
    "python software foundation license",
    "python-2.0",
    "the unlicense (unlicense)",
    "unlicense",
    "zlib",
}


def declared_license(dist: metadata.Distribution) -> str:
    """The license a distribution states, as one string ('' when it states none)."""
    meta = dist.metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression.strip()
    classifiers = [
        value.split(" :: ")[-1]
        for value in meta.get_all("Classifier") or []
        if value.startswith("License ::")
    ]
    if classifiers:
        return " AND ".join(sorted(classifiers))
    text = (meta.get("License") or "").strip()
    # a full license text pasted into the field is not a usable identifier
    return text if text and "\n" not in text and len(text) <= 80 else ""


def is_permissive(license_string: str) -> bool:
    """True when every license named in the string is on the permissive list."""
    if not license_string:
        return False
    parts = re.split(r"\s+(?:AND|OR)\s+|\s*/\s*", license_string)
    return all(
        part.strip().lower() in PERMISSIVE or part.strip("() ").lower() in PERMISSIVE
        for part in parts
    )


def load_reviewed() -> set[tuple[str, str]]:
    if not REVIEW_FILE.exists():
        return set()
    data = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    return {(entry["name"].lower(), entry["license"]) for entry in data.get("reviewed", [])}


def project_problems() -> list[str]:
    problems = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if project.get("license") != "Apache-2.0":
        problems.append('pyproject.toml [project] license is not "Apache-2.0"')
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        problems.append("LICENSE is not the Apache License, Version 2.0")
    return problems


def main() -> int:
    reviewed = load_reviewed()
    problems = project_problems()
    accepted = 0
    checked = 0
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        if name.lower() == PROJECT:
            continue
        checked += 1
        license_string = declared_license(dist)
        if is_permissive(license_string):
            continue
        if (name.lower(), license_string) in reviewed:
            accepted += 1
            continue
        shown = license_string or "no license stated"
        problems.append(f"{name} {dist.version}: {shown}")
    print(f"{checked} dependencies checked, {accepted} accepted via {REVIEW_FILE.name}.")
    if problems:
        print("Not compatible with Apache-2.0, or needs a maintainer's review:")
        for problem in problems:
            print(f"  - {problem}")
        print(f"To accept a reviewed package, add it to {REVIEW_FILE.relative_to(ROOT)}.")
        return 1
    print("All licenses are compatible with Apache-2.0.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
