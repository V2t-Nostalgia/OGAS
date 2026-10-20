"""Lossless-for-constraints ordered AST from the optional CWTools bridge."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Node:
    key: str | None
    operator: str = "="
    value: str | None = None
    children: tuple[Node, ...] | None = None
    line: int = 0
    column: int = 0
    quoted: bool = False

    @classmethod
    def from_json(cls, row: dict) -> Node:
        children = row.get("children")
        return cls(row["key"], row["operator"], row["value"],
                   None if children is None else tuple(cls.from_json(c) for c in children),
                   row["line"], row["column"], row["quoted"])

    def all(self, key: str) -> tuple[Node, ...]:
        return tuple(n for n in self.children or () if n.key == key)

    def one(self, key: str) -> Node | None:
        nodes = self.all(key)
        return nodes[0] if len(nodes) == 1 else None

    def scalar(self, key: str) -> str | None:
        node = self.one(key)
        return node.value if node else None


class ParseError(ValueError):
    pass


class CwtoolsParser:
    """One isolated parser process; bounded files and explicit parse failures.

    No fallback regex/dict parser: unsupported syntax must not become an empty,
    satisfied constraint. The process is closed even when a caller fails.
    """

    def __init__(self, bridge: Path, timeout: float = 60):
        self.bridge = bridge.resolve(strict=True)
        self.timeout = timeout
        self.process = subprocess.Popen(
            ["dotnet", str(self.bridge)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            encoding="utf-8", bufsize=1,
        )

    def parse(self, text: str, path: str = "fixture.txt") -> tuple[Node, ...]:
        if len(text.encode("utf-8")) > 16 * 1024 * 1024:
            raise ParseError("Document exceeds parser byte limit")
        process = self.process
        if process.poll() is not None:
            raise ParseError("CWTools bridge has exited")
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({"path": path, "text": text}, ensure_ascii=True) + "\n")
        process.stdin.flush()
        # Only a parser subprocess is involved. A watchdog terminates it rather
        # than allowing a malformed document to stall an offline batch forever.
        import threading
        timer = threading.Timer(self.timeout, process.kill)
        timer.start()
        try:
            line = process.stdout.readline()
        finally:
            timer.cancel()
        if not line:
            raise ParseError(f"CWTools bridge exited or timed out: {path}")
        row = json.loads(line)
        if not row.get("ok"):
            raise ParseError(f"{path}: {row.get('error', 'parse failed')}")
        return tuple(Node.from_json(n) for n in row["entries"])

    def file(self, path: Path) -> tuple[Node, ...]:
        return self.parse(path.read_text(encoding="utf-8-sig"), str(path))

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        if self.process.stdout:
            self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
