#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nostalgia and OGAS contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Snapshot research files without changing originals; publish reviewed derivatives.

The public index includes withheld files. All originals are content-addressed in
the local vault; public objects are separate. This is an export policy, not an
assertion of ownership or a native-validation classifier. No game API is used.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_digest(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Invalid SHA-256 in evidence index")
    return value


TEXT_EXTENSIONS = {".json", ".jsonl", ".ndjson", ".log", ".txt", ".md", ".csv", ".tsv",
                   ".py", ".cpp", ".h", ".hpp", ".c", ".toml", ".yaml", ".yml", ".sh", ".ps1", ".asm", ".s"}
RESTRICTED_EXTENSIONS = {".sav", ".pcap", ".pcapng", ".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg",
                        ".webp", ".dds", ".exe", ".dll", ".so", ".pdb", ".obj", ".lib", ".a", ".o", ".bin",
                        ".data", ".zip", ".tar", ".gz", ".xz", ".zst", ".npz", ".pyc", ".pyo", ".cache"}
CONTEXT_KEYS = {"build_id", "game_version", "steam_build_id", "sdk_fingerprint", "sdk_metadata_fingerprint",
                "elf_sha256", "binary_sha256", "source_commit", "git_commit", "save_sha256", "tool_versions"}
SECRET = re.compile(r'''(?ix)(?:["']?(?:api[_-]?key|password|passwd|access[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key)["']?\s*[:=]\s*["'])([^"'\r\n]{4,})(?:["'])|\b(?:ghp_|github_pat_|sk-proj-|sk-ant-)[A-Za-z0-9_-]{12,}|-----BEGIN\s+(?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9_.-]{16,}|https?://[^/\s:]+:[^@\s/]+@|--(?:password|api-key|auth-token)(?:=|\s+)\S{4,}''')
ADDRESS = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
USER_PATH = re.compile(r"(?i)(?:[A-Z]:[/\\]+Users[/\\]+)[^/\\\s\"']+|/home/[^/\s\"']+")


def neutralize(text: str, policy: dict) -> str:
    for old, new in policy.get("neutralize", {}).items():
        text = re.sub(re.escape(old), lambda _: new, text, flags=re.IGNORECASE)
    text = USER_PATH.sub("<LOCAL_USER>", text)
    def address(match):
        try:
            value = ipaddress.ip_address(match.group())
            return match.group() if value.is_loopback or value.is_unspecified else "<NETWORK_ADDRESS>"
        except ValueError:
            return match.group()
    return ADDRESS.sub(address, text)


def public_copy(path: str, data: bytes, policy: dict) -> tuple[bytes | None, str]:
    name = Path(path).name.lower()
    suffix = Path(path).suffix.lower()
    if any(re.search(pattern, path, re.I) for pattern in policy.get("withhold_paths", [])):
        return None, "private_policy_or_third_party_content"
    if suffix == ".gz" and ".jsonl" in name:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                plain = stream.read(128 * 1024 * 1024 + 1)
            if len(plain) > 128 * 1024 * 1024:
                return None, "compressed_segment_exceeds_review_budget"
            exported, disposition = public_copy(path[:path.lower().index('.jsonl')] + '.jsonl', plain, policy)
            if exported is None:
                return None, disposition
            return (data, disposition) if exported == plain else (gzip.compress(exported, compresslevel=6, mtime=0), disposition)
        except (OSError, EOFError):
            return None, "invalid_gzip_original_preserved"
    if suffix in RESTRICTED_EXTENSIONS or data.startswith((b"MZ", b"\x7fELF", b"SQLite format 3")):
        return None, "binary_save_capture_image_or_database_not_cleared_for_distribution"
    if name in {"gamestate", "meta", "ironman"} or "source-snapshot" in path and "coordinate-reuse" in path:
        return None, "game_state_or_external_source_redistribution_not_cleared"
    if ".jsonl." in name:
        suffix = ".jsonl"
    if suffix not in TEXT_EXTENSIONS and name not in {"license", "notice", "stdout", "stderr"}:
        return None, "unreviewed_format"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "non_utf8_unreviewed"
    if "\x00" in text or SECRET.search(text):
        return None, "possible_credentials_or_binary_content"
    if any(secret and secret in text for secret in policy.get("never_publish", [])):
        return None, "private_value_present"
    changed = neutralize(text, policy)
    # JSON must remain parseable after path redaction; sanitize string values,
    # rather than substituting inside JSON escapes and damaging the evidence.
    if suffix in {".json", ".jsonl", ".ndjson"} and changed != text:
        try:
            def transform(item):
                if isinstance(item, str):
                    return neutralize(item, policy)
                if isinstance(item, list):
                    return [transform(x) for x in item]
                if isinstance(item, dict):
                    return {neutralize(k, policy): transform(v) for k, v in item.items()}
                return item
            if suffix == ".json":
                changed = json.dumps(transform(json.loads(text)), ensure_ascii=True, indent=2) + "\n"
            else:
                changed = "\n".join(json.dumps(transform(json.loads(line)), ensure_ascii=True) for line in text.splitlines() if line.strip()) + "\n"
        except (ValueError, RecursionError):
            return None, "invalid_or_unreviewed_json_with_private_paths"
    if changed == text:
        return data, "public_original"
    return changed.encode("utf-8"), "public_redacted_derivative_original_retained"


def context(data: bytes, suffix: str) -> list[dict]:
    if suffix != ".json" or len(data) > 32 * 1024 * 1024:
        return []
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        return []
    found, budget = [], 4096
    def walk(item, pointer="", depth=0):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 6 or len(found) >= 32:
            return
        if isinstance(item, dict):
            for key, val in item.items():
                at = pointer + "/" + str(key)
                if key in CONTEXT_KEYS and isinstance(val, (str, int, dict)):
                    found.append({"json_pointer": at, "reported_value": val})
                if isinstance(val, (dict, list)):
                    walk(val, at, depth + 1)
        elif isinstance(item, list):
            for index, val in enumerate(item[:32]):
                walk(val, pointer + "/" + str(index), depth + 1)
    walk(value)
    return found


def put(store: Path, data: bytes) -> str:
    digest = sha(data)
    target = store / digest[:2] / (digest + ".gz")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(gzip.compress(data, compresslevel=6, mtime=0))
    return digest


def read_snapshot(path: Path) -> tuple[bytes, bool]:
    for _ in range(3):
        before = path.stat()
        data = path.read_bytes()
        after = path.stat()
        if before.st_size == after.st_size == len(data) and before.st_mtime_ns == after.st_mtime_ns:
            return data, True
    return data, False


def build(roots: list[tuple[str, Path]], output: Path, policy: dict, source_commit: str, external_indexes=()) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    public, vault = output / "public", output / "local-vault"
    public.mkdir()
    vault.mkdir()
    counts, rows, original_rows, root_rows = Counter(), [], [], []
    for label, root in roots:
        root = root.resolve(strict=True)
        if root == output.resolve() or root in output.resolve().parents:
            raise ValueError("Archive output must not be contained in an input root")
        files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        root_rows.append({"label": label, "files_at_enumeration": len(files)})
        for path in files:
            original = label + "/" + path.relative_to(root).as_posix()
            alias = neutralize(original, policy).replace("<", "_").replace(">", "_")
            data, stable = read_snapshot(path)
            raw_sha = put(vault / "objects", data)
            exported, disposition = public_copy(original, data, policy)
            row = {"path": alias, "entry": "paths/" + sha(alias.encode())[:2] + "/" + sha(alias.encode()) + ".md",
                   "original_sha256": raw_sha, "original_bytes": len(data), "original_location": "local_vault",
                   "stable_snapshot": stable, "access": disposition,
                   "validation_state": "not_inferred_from_format_or_IsValid",
                   "public_sha256": None, "object": None, "reported_context": []}
            if exported is not None:
                digest = put(public / "objects", exported)
                row.update(public_sha256=digest, object="objects/" + digest[:2] + "/" + digest + ".gz",
                           reported_context=context(exported, path.suffix.lower()))
                counts["public_bytes_uncompressed"] += len(exported)
            counts[disposition] += 1
            counts["files"] += 1
            counts["original_bytes"] += len(data)
            if not stable:
                counts["unstable_snapshots"] += 1
            original_rows.append({**row, "original_path": original, "source_path": str(path)})
            rows.append(row)
            if counts["files"] % 200 == 0:
                print(json.dumps({"files_processed": counts["files"], "original_bytes": counts["original_bytes"]}), flush=True)
    by_path = {row['path']: row for row in rows}
    originals_by_path = {row['path']: row for row in original_rows}
    for external in external_indexes:
        for line in external.read_text(encoding='utf-8').splitlines():
            original = json.loads(line)
            alias = neutralize('remote/' + original['path'], policy).replace('<', '_').replace('>', '_')
            if alias in by_path:
                if by_path[alias]['original_sha256'] != original.get('sha256'):
                    raise ValueError('Remote transferred snapshot differs from original index')
                stable = by_path[alias]['stable_snapshot'] and original.get('stable', False)
                if by_path[alias]['stable_snapshot'] and not stable:
                    counts['unstable_snapshots'] += 1
                by_path[alias]['stable_snapshot'] = stable
                originals_by_path[alias]['stable_snapshot'] = stable
                originals_by_path[alias]['remote_record'] = original
                continue
            if not original.get('sha256'):
                counts['remote_unreadable_files'] += 1
            row = {'path': alias, 'entry': 'paths/' + sha(alias.encode())[:2] + '/' + sha(alias.encode()) + '.md',
                   'original_sha256': original.get('sha256'), 'original_bytes': original.get('size'),
                   'original_location': 'remote_retained_original', 'stable_snapshot': original.get('stable', False),
                   'access': 'remote_restricted_original_not_published', 'validation_state': 'not_inferred_from_format_or_IsValid',
                   'public_sha256': None, 'object': None, 'reported_context': []}
            rows.append(row)
            original_rows.append({**row, 'source_path': original.get('source_path'), 'remote_record': original})
            counts[row['access']] += 1
            counts['files'] += 1
            counts['original_bytes'] += original.get('size', 0)
    if len({r['path'] for r in rows}) != len(rows):
        raise ValueError('Neutralized archive paths collide; do not publish')
    write_jsonl(vault / "original-index.jsonl", original_rows)
    write_jsonl(public / "index.jsonl", rows)
    summary = {"schema_version": "ogas.evidence_archive.v1", "created_at_utc": datetime.now(timezone.utc).isoformat(),
               "archive_source_commit": source_commit, "historical_source_binding": "per_artifact_context_or_unknown; never retroactively assigned",
               "roots": root_rows, "counts": dict(counts), "index_sha256": sha((public / "index.jsonl").read_bytes()),
               "unique_public_objects": len(list((public / "objects").rglob("*.gz"))),
               "original_index_access": "local_restricted; originals not deleted",
               "original_index_sha256": sha((vault / "original-index.jsonl").read_bytes()),
               "evidence_levels": "raw observations, automated reports, human interpretations and live verification remain distinct"}
    (public / "ARCHIVE.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        pointer = public / row['entry']
        pointer.parent.mkdir(parents=True, exist_ok=True)
        link = "No public original download. Retained in the restricted local vault."
        if row["object"]:
            import os
            relative = Path(os.path.relpath(public / row["object"], pointer.parent)).as_posix()
            link = f"[Download the gzip research object]({relative}). Decompress and verify the public SHA-256."
        text = f"# Research Evidence\n\nPath: `{row['path']}`\n\nAccess: `{row['access']}`\n\nOriginal SHA-256: `{row['original_sha256']}`\n\nPublic SHA-256: `{row['public_sha256']}`\n\n{link}\n\nA redacted derivative is not the original. This entry does not promote a Command or establish causal pairing.\n"
        pointer.write_text(text, encoding="utf-8")
    return summary


def write_jsonl(path: Path, rows: list[dict]):
    with path.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")


def verify(index: Path, objects: Path, original: bool = False) -> dict:
    seen, count, total, remote = set(), 0, 0, 0
    for line in index.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        digest = row["original_sha256"] if original else row["public_sha256"]
        if original and row.get('original_location') == 'remote_retained_original':
            remote += 1
            continue
        if not digest:
            continue
        checked_digest(digest)
        if digest not in seen:
            with gzip.open(objects / digest[:2] / (digest + ".gz"), "rb") as stream:
                data = stream.read()
            if sha(data) != digest:
                raise ValueError("Corrupt evidence object: " + digest)
            seen.add(digest)
            total += len(data)
        count += 1
    return {"mapped_files": count, "verified_objects": len(seen), "verified_uncompressed_bytes": total,
            'remote_originals_not_locally_reverified': remote}


def restore(index: Path, objects: Path, output: Path, original: bool = False):
    output.mkdir(parents=True, exist_ok=False)
    restored, remote = 0, 0
    for line in index.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if original and row.get('original_location') == 'remote_retained_original':
            remote += 1
            continue
        digest = row['original_sha256'] if original else row['public_sha256']
        if not digest:
            continue
        checked_digest(digest)
        target = output / (row.get('original_path', row['path']) if original else row['path'])
        if not target.resolve().is_relative_to(output.resolve()):
            raise ValueError("Unsafe archive path")
        with gzip.open(objects / digest[:2] / (digest + ".gz"), "rb") as stream:
            data = stream.read()
        if sha(data) != digest:
            raise ValueError("Corrupt evidence object")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        restored += 1
    return {'restored_files': restored, 'remote_originals_not_restored': remote}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    export = sub.add_parser("build")
    export.add_argument("--root", action="append", required=True, help="LABEL=existing-directory")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--source-commit", required=True)
    export.add_argument("--private-policy", type=Path)
    export.add_argument("--external-index", type=Path, action="append", default=[])
    export.add_argument("--sensitive-input", action="store_true", help="Read an extra secret using getpass, never persist it")
    check = sub.add_parser("verify")
    check.add_argument("--index", type=Path, required=True)
    check.add_argument("--objects", type=Path, required=True)
    check.add_argument("--original", action="store_true")
    unpack = sub.add_parser("restore")
    unpack.add_argument("--index", type=Path, required=True)
    unpack.add_argument("--objects", type=Path, required=True)
    unpack.add_argument("--output", type=Path, required=True)
    unpack.add_argument("--original", action="store_true", help="Use the restricted original index/vault, never public derivatives")
    args = parser.parse_args()
    if args.mode == "build":
        roots = [(label, Path(value)) for label, value in (r.split("=", 1) for r in args.root)]
        policy = json.loads(args.private_policy.read_text(encoding="utf-8")) if args.private_policy else {}
        if args.sensitive_input:
            import getpass
            policy.setdefault('never_publish', []).append(getpass.getpass('Private value to exclude (not stored): '))
        result = build(roots, args.output, policy, args.source_commit, args.external_index)
    elif args.mode == "verify":
        result = verify(args.index, args.objects, args.original)
    else:
        result = restore(args.index, args.objects, args.output, args.original)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
