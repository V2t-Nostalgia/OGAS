#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nostalgia and OGAS contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Check the actual staged source tree, not ignored local research outputs."""

from __future__ import annotations

import argparse
import json
import posixpath
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_PAIRS = [("README.md", "README.zh-CN.md"),
                  ("CONTRIBUTING.md", "CONTRIBUTING.zh-CN.md"),
                  ("docs/DEVELOPMENT.md", "docs/DEVELOPMENT.zh-CN.md")]
FORBIDDEN_ROOTS = {".runtime-evidence", ".publication", ".tmp", ".runtime-analysis", "build", "dist",
                   "artifacts", "captures", "saves", "runtime", "logs", "databases", "state"}
FORBIDDEN_SUFFIXES = {".sav", ".pcap", ".pcapng", ".sqlite", ".sqlite3", ".exe", ".dll", ".so",
                      ".pdb", ".obj", ".pyc", ".pem", ".key"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def staged_files() -> dict[str, bytes]:
    names = git("ls-files", "-z").decode().split("\0")
    return {name: git("show", ":" + name) for name in names if name}


def relative_links(name: str, text: str):
    # Fenced shell transcripts contain illustrative paths, not Markdown links.
    text = re.sub(r"(?ms)^\s*(```|~~~).*?^\s*\1[^\n]*$", "", text)
    for match in re.finditer(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", text):
        target = match.group(1).strip("<>")
        if target.startswith("#") or urlsplit(target).scheme or target.startswith("//"):
            continue
        target = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if target:
            yield posixpath.normpath(posixpath.join(posixpath.dirname(name), target)), target


def audit(files: dict[str, bytes]) -> dict:
    errors, historical, links = [], [], 0
    for name, body in files.items():
        path = Path(name)
        if path.parts[0] in FORBIDDEN_ROOTS or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append({"file": name, "reason": "private_or_generated_file_in_source_index"})
        if len(body) > 50 * 1024 * 1024:
            errors.append({"file": name, "reason": "large_file_belongs_in_evidence_archive"})
        if path.suffix.lower() != ".md":
            continue
        text = body.decode("utf-8")
        old = name.startswith("docs/reference/") or (name.startswith("docs/releases/") and "v0.6.0-alpha.1" not in name)
        for resolved, target in relative_links(name, text):
            links += 1
            exists = resolved in files or any(p.startswith(resolved.rstrip("/") + "/") for p in files)
            if not exists:
                issue = {"file": name, "target": target, "reason": "not_in_staged_source_tree"}
                (historical if old else errors).append(issue)
    for english, chinese in LANGUAGE_PAIRS:
        for left, right in ((english, chinese), (chinese, english)):
            if left not in files or right not in files:
                errors.append({"file": left, "reason": "missing_language_pair"})
                continue
            relative = posixpath.relpath(right, posixpath.dirname(left) or ".")
            if f"]({relative})" not in files[left].decode():
                errors.append({"file": left, "reason": "missing_language_switch"})
            if "v0.6.0-alpha.1" not in files[left].decode():
                errors.append({"file": left, "reason": "missing_current_version"})
    for name in ("pyproject.toml", "src/iag/__init__.py"):
        if "0.6.0a1" not in files.get(name, b"").decode():
            errors.append({"file": name, "reason": "python_version_mismatch"})
    for name in ("CITATION.cff", ".zenodo.json"):
        if "0.6.0-alpha.1" not in files.get(name, b"").decode():
            errors.append({"file": name, "reason": "publication_version_mismatch"})
    return {"source_files": len(files), "markdown_links_checked": links, "errors": errors,
            "historical_links_not_rewritten": historical}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(staged_files())
    rendered = json.dumps(result, ensure_ascii=True, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(rendered + "\n")
    print(rendered)
    return bool(result["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
