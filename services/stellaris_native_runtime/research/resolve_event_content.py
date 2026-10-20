#!/usr/bin/env python3
"""Resolve event-state localization keys without calling game render functions."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


SCHEMA = "iag.stellaris.event_content_catalog.v1"
LOCALIZATION_LINE = re.compile(
    r'^\s*([^\s:#]+):(?:\d+)?\s+"(.*)"\s*(?:#.*)?$'
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    opener: Any = gzip.open if path.suffix == ".gz" else Path.open
    arguments = ("rt",) if path.suffix == ".gz" else ()
    keywords = {"encoding": "utf-8", "errors": "replace"}
    with opener(path, *arguments, **keywords) as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def collect_event_definitions(paths: Iterable[Path]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for path in paths:
        for event in iter_jsonl(path):
            if event.get("content_included") is not True:
                continue
            script_key = str(event.get("event_or_type_key") or "")
            if not script_key:
                script_key = f"#{event.get('event_definition_id', 'unknown')}"
            options = event.get("options")
            option_values = options if isinstance(options, list) else []
            definitions[script_key] = {
                "event_definition_id": event.get("event_definition_id"),
                "title_key": str(event.get("title_key") or ""),
                "description_key": str(event.get("description_key") or ""),
                "option_keys": [
                    str(option.get("text_key"))
                    for option in option_values
                    if isinstance(option, dict) and option.get("text_key")
                ],
                "text_truncated": event.get("text_truncated") is True,
            }
    return definitions


def parse_localization_stream(
    stream: TextIO,
    source: str,
    wanted: set[str],
    resolved: dict[str, dict[str, str]],
) -> None:
    for line in stream:
        match = LOCALIZATION_LINE.match(line.rstrip("\r\n"))
        if match is None or match.group(1) not in wanted:
            continue
        resolved[match.group(1)] = {
            "text": match.group(2).replace(r'\"', '"'),
            "source": source,
        }


def localization_loose_files(game_root: Path, language: str) -> Iterator[Path]:
    for path in game_root.rglob("*.yml"):
        normalized = path.as_posix().lower()
        if "/localisation/" in normalized and f"/{language.lower()}/" in normalized:
            yield path


def resolve_localization(
    game_root: Path,
    language: str,
    wanted: set[str],
) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for path in sorted(localization_loose_files(game_root, language)):
        try:
            with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
                parse_localization_stream(
                    stream, str(path.relative_to(game_root)), wanted, resolved
                )
        except OSError:
            continue
    for archive_path in sorted((game_root / "dlc").rglob("*.zip")):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = sorted(
                    name
                    for name in archive.namelist()
                    if name.lower().endswith(".yml")
                    and "/localisation/" in f"/{name.lower()}"
                    and f"/{language.lower()}/" in f"/{name.lower()}"
                )
                for member in members:
                    with archive.open(member) as raw:
                        lines = (
                            line.decode("utf-8-sig", errors="replace")
                            for line in raw
                        )
                        parse_localization_stream(
                            lines,
                            f"{archive_path.relative_to(game_root)}!{member}",
                            wanted,
                            resolved,
                        )
        except (OSError, zipfile.BadZipFile):
            continue
    return resolved


def resolved_value(
    key: str, localization: dict[str, dict[str, str]]
) -> dict[str, Any]:
    value = localization.get(key)
    return {
        "key": key,
        "resolved": value is not None,
        "text": "" if value is None else value["text"],
        "source": "" if value is None else value["source"],
    }


def build_catalog(
    definitions: dict[str, dict[str, Any]],
    localization: dict[str, dict[str, str]],
    language: str,
) -> dict[str, Any]:
    events: dict[str, Any] = {}
    unresolved: set[str] = set()
    for script_key, definition in sorted(definitions.items()):
        title = resolved_value(definition["title_key"], localization)
        description = resolved_value(definition["description_key"], localization)
        options = [
            resolved_value(key, localization) for key in definition["option_keys"]
        ]
        for value in [title, description, *options]:
            if value["key"] and not value["resolved"]:
                unresolved.add(value["key"])
        events[script_key] = {
            **definition,
            "title": title,
            "description": description,
            "options": options,
        }
    return {
        "schema": SCHEMA,
        "generated_at": utc_now(),
        "language": language,
        "event_count": len(events),
        "unresolved_keys": sorted(unresolved),
        "dynamic_rendering_note": (
            "Localization is intentionally preserved as a template. Scope tokens, "
            "scripted localization, and runtime substitutions are not evaluated."
        ),
        "events": events,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--states",
        type=Path,
        nargs="+",
        default=[Path("/tmp/iag-stellaris-state-probe.jsonl")],
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--language", default="simp_chinese")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    definitions = collect_event_definitions(args.states)
    wanted = {
        key
        for definition in definitions.values()
        for key in (
            definition["title_key"],
            definition["description_key"],
            *definition["option_keys"],
        )
        if key
    }
    localization = resolve_localization(args.game_root, args.language, wanted)
    catalog = build_catalog(definitions, localization, args.language)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"resolved {len(catalog['events'])} events; "
        f"unresolved localization keys: {len(catalog['unresolved_keys'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
