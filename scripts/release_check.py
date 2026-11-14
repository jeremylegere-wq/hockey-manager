#!/usr/bin/env python3
"""Release and repository checks (standard library only).

    python3 scripts/release_check.py                 repository checks and Python 3.9 syntax
    python3 scripts/release_check.py --tag v0.62     the same, plus: the tag matches VERSION and CHANGELOG.md has
                                                      a dated section for it
    python3 scripts/release_check.py --notes 0.62    print that section of CHANGELOG.md (the release notes)

The authoritative version is VERSION in hs/ui/settings.py. A release tag is "v" + VERSION (VERSION "0.62" is tag v0.62).
Exit code 0 means every check passed; each failure is printed with what to change.
"""
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_PYTHON = (3, 9)                      # README: "Python 3.9 or newer"
# Files that may be tracked even though *.db and packs/* are otherwise kept out (see .gitignore).
PACK_OK = ("packs/README.md", "packs/example_fictional/")


def version() -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', (ROOT / "hs/ui/settings.py").read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("could not find VERSION in hs/ui/settings.py")
    return m.group(1)


def changelog_section(ver: str) -> str | None:
    """The body of '## [ver] - date' in CHANGELOG.md, or None."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[%s\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)" % re.escape(ver), text, re.M | re.S)
    return m.group(1).strip() if m else None


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def check(tag: str | None) -> list[str]:
    problems: list[str] = []
    ver = version()

    # 1. every Python file parses with the oldest supported grammar
    for f in tracked():
        if f.endswith(".py"):
            try:
                ast.parse((ROOT / f).read_text(encoding="utf-8"), f, feature_version=MIN_PYTHON)
            except SyntaxError as e:
                problems.append(f"{f}:{e.lineno}: not valid Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}: {e.msg}")

    # 2. nothing that must stay private is tracked: saves, worlds and packs derived from third-party data
    for f in tracked():
        if f.endswith((".db", ".db-wal", ".db-shm")) or f.startswith(("saves/", "save/", "worlds/", ".runtime/")):
            problems.append(f"{f}: generated or personal data is tracked; remove it (git rm --cached)")
        if f.startswith("packs/") and not f.startswith(PACK_OK):
            problems.append(f"{f}: only packs/README.md and packs/example_fictional/ may be published")

    # 3. the changelog has an Unreleased section
    log = ROOT / "CHANGELOG.md"
    if not log.exists():
        problems.append("CHANGELOG.md is missing")
    elif "## [Unreleased]" not in log.read_text(encoding="utf-8"):
        problems.append("CHANGELOG.md has no '## [Unreleased]' section")

    # 4. a tag names the version in the code and has release notes
    if tag:
        if tag != "v" + ver:
            problems.append(f"tag {tag} does not match VERSION {ver!r} in hs/ui/settings.py (expected v{ver})")
        if log.exists():
            body = changelog_section(ver)
            if body is None:
                problems.append(f"CHANGELOG.md has no '## [{ver}] - YYYY-MM-DD' section")
            elif not body:
                problems.append(f"CHANGELOG.md section [{ver}] is empty")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", help="a release tag to validate, such as v0.62")
    ap.add_argument("--notes", metavar="VERSION", help="print the CHANGELOG.md section for VERSION and exit")
    a = ap.parse_args(argv)
    if a.notes:
        body = changelog_section(a.notes)
        if not body:
            print(f"no CHANGELOG.md section for {a.notes}", file=sys.stderr)
            return 1
        print(body)
        return 0
    problems = check(a.tag)
    for p in problems:
        print("FAIL", p)
    if problems:
        return 1
    print(f"ok: version {version()}" + (f", tag {a.tag}" if a.tag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
