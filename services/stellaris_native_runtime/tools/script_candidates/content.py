"""External content index with explicit overlay provenance, never 'loaded DB'."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .syntax import CwtoolsParser, Node, ParseError


@dataclass(frozen=True)
class ContentLayer:
    root: Path
    replace_paths: tuple[str, ...] = ()


@dataclass
class Content:
    entries: dict[tuple[str, str], Node] = field(default_factory=dict)
    sources: dict[tuple[str, str], str] = field(default_factory=dict)
    ambiguous: set[tuple[str, str]] = field(default_factory=set)
    files: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    engine_loaded: bool = False
    definition_families: dict[str, str] = field(default_factory=dict)

    def family(self, name: str) -> dict[str, Node]:
        return {key: node for (family, key), node in self.entries.items() if family == name and (family, key) not in self.ambiguous}

    @property
    def fingerprint(self) -> str:
        import json
        return hashlib.sha256(json.dumps([self.files, self.definition_families], sort_keys=True).encode()).hexdigest()


def load_content(parser: CwtoolsParser, layers: tuple[ContentLayer, ...], families: tuple[str, ...]) -> Content:
    """Resolve exact file overlays. Duplicate definitions across files stay unknown.

    Layers must be supplied in actual load order by a trusted inventory. When
    that order or archives are unavailable, the output is external evidence only.
    No guesses about per-definition 'last one wins' semantics are made.
    """
    content = Content()
    selected: dict[str, tuple[int, Path, str]] = {}
    for layer_index, layer in enumerate(layers):
        root = layer.root.resolve(strict=True)
        for replacement in layer.replace_paths:
            relative = PurePosixPath(replacement.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid replace_path")
            prefix = str(relative).rstrip("/") + "/"
            selected = {key: value for key, value in selected.items() if not key.startswith(prefix)}
        for family in families:
            for path in sorted((root / "common" / family).glob("**/*.txt")):
                if not path.resolve().is_relative_to(root):
                    raise ValueError("Content symlink escapes declared layer")
                selected[path.relative_to(root).as_posix()] = (layer_index, path, family)
    definitions = defaultdict(list)
    for relative, (layer_index, path, family) in sorted(selected.items()):
        raw = path.read_bytes()
        identity = {"path": str(path), "relative": relative, "layer": layer_index,
                    "sha256": hashlib.sha256(raw).hexdigest()}
        content.files.append(identity)
        try:
            nodes = parser.parse(raw.decode("utf-8-sig"), str(path))
        except (ParseError, UnicodeError) as error:
            content.errors.append(identity | {"error": str(error)})
            continue
        for node in nodes:
            if node.key and node.children is not None and not node.key.startswith("@"):
                definitions[family, node.key].append((node, str(path)))
    for key, rows in definitions.items():
        if len(rows) != 1:
            content.ambiguous.add(key)
            continue
        content.entries[key], content.sources[key] = rows[0]
    return content
