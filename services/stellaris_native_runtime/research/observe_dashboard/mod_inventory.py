from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from .common import load_json, read_last_jsonl, utc_now


SEMANTIC_SUFFIXES = {
    ".txt",
    ".gui",
    ".gfx",
    ".asset",
    ".yml",
    ".yaml",
    ".csv",
    ".lua",
}
DEFINITION_CATEGORIES = {
    "buildings": "building",
    "technology": "technology",
    "technologies": "technology",
    "ship_sizes": "ship",
    "section_templates": "ship",
    "component_templates": "ship",
    "ship_behaviors": "ship",
    "situations": "situation",
    "edicts": "edict",
    "policies": "policy",
    "traditions": "tradition",
    "ascension_perks": "ascension_perk",
    "civics": "civic",
    "governments": "government",
    "species_rights": "species_rights",
}
_ASSIGNMENT = re.compile(
    r'^\s*([A-Za-z0-9_.:@-]+)\s*=\s*(?:"([^"]*)"|([^\s#{}]+))'
)
_TOP_LEVEL_BLOCK = re.compile(r"^\s*([A-Za-z0-9_.:-]+)\s*=\s*\{")
_EVENT_ID = re.compile(r"\bid\s*=\s*\"?([A-Za-z0-9_.:-]+)\"?")


def parse_descriptor(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return {"descriptor": str(path), "read_error": True}
    result: dict[str, Any] = {"descriptor": str(path)}
    tags: list[str] = []
    in_tags = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("tags") and "{" in stripped:
            in_tags = True
            continue
        if in_tags:
            if "}" in stripped:
                in_tags = False
            else:
                match = re.search(r'"([^"]+)"', stripped)
                if match:
                    tags.append(match.group(1))
            continue
        match = _ASSIGNMENT.match(line)
        if match:
            key, quoted_value, bare_value = match.groups()
            value = quoted_value if quoted_value is not None else bare_value
            if key in {"name", "path", "remote_file_id", "version", "supported_version"}:
                result[key] = value
    result["tags"] = tags
    result["descriptor_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return result


def _strip_comments(line: str) -> str:
    quoted = False
    escaped = False
    output: list[str] = []
    for character in line:
        if escaped:
            output.append(character)
            escaped = False
        elif character == "\\" and quoted:
            output.append(character)
            escaped = True
        elif character == '"':
            quoted = not quoted
            output.append(character)
        elif character == "#" and not quoted:
            break
        else:
            output.append(character)
    return "".join(output)


def _brace_delta(text: str) -> int:
    quoted = False
    escaped = False
    delta = 0
    for character in text:
        if escaped:
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted and character == "{":
            delta += 1
        elif not quoted and character == "}":
            delta -= 1
    return delta


def external_definition_index(root: Path, max_samples: int = 40) -> dict[str, Any]:
    """Index external script definitions without claiming the engine loaded them."""
    counts: Counter[str] = Counter()
    samples: dict[str, list[str]] = defaultdict(list)
    files_scanned = 0
    parse_errors = 0
    try:
        paths = sorted(path for path in root.rglob("*") if path.is_file())
    except OSError:
        paths = []
    for path in paths:
        if path.suffix.lower() != ".txt":
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        category: str | None = None
        if parts and parts[0] == "events":
            category = "event"
        elif len(parts) > 1 and parts[0] == "common":
            category = DEFINITION_CATEGORIES.get(parts[1])
        if category is None:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            parse_errors += 1
            continue
        files_scanned += 1
        if category == "event":
            identifiers = _EVENT_ID.findall("\n".join(_strip_comments(v) for v in text.splitlines()))
        else:
            identifiers: list[str] = []
            depth = 0
            for raw_line in text.splitlines():
                line = _strip_comments(raw_line)
                if depth == 0:
                    match = _TOP_LEVEL_BLOCK.match(line)
                    if match and not match.group(1).startswith("@"):
                        identifiers.append(match.group(1))
                depth = max(0, depth + _brace_delta(line))
        unique = sorted(set(identifiers))
        counts[category] += len(unique)
        for identifier in unique:
            if len(samples[category]) < max_samples:
                samples[category].append(identifier)
    return {
        "provenance": "external_mod_files",
        "engine_loaded": False,
        "parser": "bounded_clausewitz_text_index_v1",
        "files_scanned": files_scanned,
        "parse_errors": parse_errors,
        "counts": dict(sorted(counts.items())),
        "samples": dict(sorted(samples.items())),
    }


def _iter_files(root: Path, max_files: int) -> Iterable[Path]:
    count = 0
    try:
        paths = root.rglob("*")
        for path in paths:
            if count >= max_files:
                break
            try:
                if not path.is_file() or path.is_symlink():
                    continue
            except OSError:
                continue
            count += 1
            yield path
    except OSError:
        return


def fingerprint_tree(
    root: Path, *, max_files: int = 100_000, max_content_bytes: int = 512 * 1024 * 1024
) -> dict[str, Any]:
    tree_digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    semantic_digest = hashlib.sha256()
    files = 0
    bytes_seen = 0
    content_bytes_hashed = 0
    semantic_bytes_hashed = 0
    truncated = False
    for path in _iter_files(root, max_files):
        try:
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        files += 1
        bytes_seen += stat.st_size
        tree_digest.update(
            f"{relative}\0{stat.st_size}\0{stat.st_mtime_ns}\n".encode("utf-8")
        )
        remaining = max_content_bytes - content_bytes_hashed
        hash_all = remaining > 0
        hash_semantic = path.suffix.lower() in SEMANTIC_SUFFIXES
        if not hash_all and not hash_semantic:
            truncated = True
            continue
        try:
            with path.open("rb") as stream:
                content_digest.update(relative.encode("utf-8") + b"\0")
                if hash_semantic:
                    semantic_digest.update(relative.encode("utf-8") + b"\0")
                while chunk := stream.read(1024 * 1024):
                    if hash_all:
                        allowed = chunk[:remaining]
                        content_digest.update(allowed)
                        content_bytes_hashed += len(allowed)
                        remaining -= len(allowed)
                        if len(allowed) != len(chunk):
                            hash_all = False
                            truncated = True
                    if hash_semantic:
                        semantic_digest.update(chunk)
                        semantic_bytes_hashed += len(chunk)
        except OSError:
            truncated = True
    if files >= max_files:
        truncated = True
    return {
        "root": str(root),
        "file_count": files,
        "total_bytes": bytes_seen,
        "tree_fingerprint_sha256": tree_digest.hexdigest(),
        "bounded_content_fingerprint_sha256": content_digest.hexdigest(),
        "content_bytes_hashed": content_bytes_hashed,
        "content_complete": not truncated and content_bytes_hashed == bytes_seen,
        "semantic_content_fingerprint_sha256": semantic_digest.hexdigest(),
        "semantic_bytes_hashed": semantic_bytes_hashed,
        "truncated": truncated,
    }


def _extract_block(text: str, key: str) -> str | None:
    match = re.search(rf"(?:^|\n)\s*{re.escape(key)}\s*=\s*\{{", text)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if escaped:
            escaped = False
        elif character == "\\" and quoted:
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif not quoted and character == "{":
            depth += 1
        elif not quoted and character == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return None


def read_save_mod_evidence(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"available": False, "reason": "no archived save was found"}
    try:
        with zipfile.ZipFile(path) as archive:
            text = archive.read("meta").decode("utf-8-sig", errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return {"available": False, "reason": f"cannot read save metadata: {path}"}
    block = _extract_block(text, "mods")
    mods = re.findall(r'"([^"]+)"', block or "")
    version_match = re.search(r'(?:^|\n)\s*version\s*=\s*"([^"]+)"', text)
    date_match = re.search(r'(?:^|\n)\s*date\s*=\s*"?([0-9.]+)"?', text)
    return {
        "available": True,
        "provenance": "save_meta",
        "save": str(path),
        "declared_mods": mods,
        "game_version": version_match.group(1) if version_match else None,
        "game_date": date_match.group(1) if date_match else None,
        "meaning": "mods declared by this saved session",
    }


def elf_build_id(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    try:
        result = subprocess.run(
            ["readelf", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", result.stdout)
    return match.group(1).lower() if match else None


def sha256_path(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


class ModInventoryCollector:
    def __init__(
        self,
        user_data: Path,
        *,
        game_binary: Path | None = None,
        capture_root: Path | None = None,
        max_files: int = 100_000,
        max_content_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self.user_data = user_data
        self.game_binary = game_binary
        self.capture_root = capture_root
        self.max_files = max_files
        self.max_content_bytes = max_content_bytes

    def collect(self) -> dict[str, Any]:
        config_path = self.user_data / "dlc_load.json"
        config = load_json(config_path, {})
        enabled = config.get("enabled_mods", []) if isinstance(config, dict) else []
        if not isinstance(enabled, list):
            enabled = []
        mods: list[dict[str, Any]] = []
        for load_index, raw in enumerate(enabled):
            if not isinstance(raw, str):
                continue
            descriptor_path = self.user_data / raw
            descriptor = parse_descriptor(descriptor_path)
            root_value = descriptor.get("path")
            root = Path(root_value).expanduser() if isinstance(root_value, str) else None
            record = {
                "load_index": load_index,
                "launcher_entry": raw,
                **descriptor,
            }
            if root is not None and root.is_dir():
                record["fingerprints"] = fingerprint_tree(
                    root,
                    max_files=self.max_files,
                    max_content_bytes=self.max_content_bytes,
                )
                record["external_definitions"] = external_definition_index(root)
            else:
                record["fingerprints"] = {"available": False, "root": str(root)}
                record["external_definitions"] = {
                    "provenance": "external_mod_files",
                    "engine_loaded": False,
                    "available": False,
                }
            mods.append(record)
        latest_save_path: Path | None = None
        if self.capture_root is not None:
            latest = read_last_jsonl(self.capture_root / "save_index.jsonl")
            archive = latest.get("archive") if latest else None
            if isinstance(archive, str):
                latest_save_path = Path(archive)
        save_evidence = read_save_mod_evidence(latest_save_path)
        save_declared = save_evidence.get("declared_mods", [])
        configured = [value for value in enabled if isinstance(value, str)]
        inventory_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    {
                        "entry": item.get("launcher_entry"),
                        "descriptor": item.get("descriptor_sha256"),
                        "semantic": item.get("fingerprints", {}).get(
                            "semantic_content_fingerprint_sha256"
                        ),
                    }
                    for item in mods
                ],
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schema": "iag.stellaris.mod_inventory.v1",
            "observed_at": utc_now(),
            "launcher_configuration": {
                "path": str(config_path),
                "available": config_path.is_file(),
                "enabled_mods_in_load_order": enabled,
                "disabled_dlcs": config.get("disabled_dlcs", [])
                if isinstance(config, dict)
                else [],
                "meaning": "launcher configuration, not proof of current process state",
            },
            "save_evidence": save_evidence,
            "game_binary": str(self.game_binary) if self.game_binary else None,
            "elf_build_id": elf_build_id(self.game_binary),
            "game_binary_sha256": sha256_path(self.game_binary),
            "game_version": save_evidence.get("game_version"),
            "game_version_provenance": "save_meta"
            if save_evidence.get("game_version")
            else "unavailable",
            "mods": mods,
            "inventory_fingerprint_sha256": inventory_fingerprint,
            "actual_loaded_definitions": {
                "available": False,
                "reason": (
                    "External files and save-declared mods do not enumerate the "
                    "definitions instantiated by the running engine."
                ),
            },
            "attribution_policy": {
                "per_mod_causality": "unknown_without_controlled_run",
                "new_commands": "correlated_with_complete_mod_set_only",
            },
            "configured_vs_save": {
                "matches": bool(save_evidence.get("available"))
                and configured == save_declared,
                "configured_not_in_save": sorted(set(configured) - set(save_declared)),
                "save_not_configured_now": sorted(set(save_declared) - set(configured)),
                "note": "order is retained separately; set differences do not prove load failure",
            },
        }
