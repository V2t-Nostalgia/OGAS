#!/usr/bin/env python3
"""Load the exact-build passive discovery probes with one reviewed GDB attach."""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path


EXPECTED_BUILD_ID = "c6969e60fd81d738948222a94c0b5a0841abbffc"
PROBES = (
    ("libiag_stellaris_command_probe.so", "iag_stellaris_command_probe_status"),
    ("libiag_stellaris_payload_probe.so", "iag_stellaris_payload_probe_status"),
    (
        "libiag_stellaris_event_state_probe.so",
        "iag_stellaris_event_state_probe_status",
    ),
)


def elf_build_id(executable: Path) -> str:
    result = subprocess.run(
        ["readelf", "-n", str(executable)],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"Build ID:\s*([0-9a-fA-F]+)", result.stdout)
    if match is None:
        raise RuntimeError(f"no ELF Build ID in {executable}")
    return match.group(1).lower()


def gdb_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_gdb(
    pid: int,
    executable: Path,
    libraries: list[tuple[Path, str]],
) -> str:
    executable_path = gdb_string(str(executable))
    lines = [
        "set pagination off",
        "set confirm off",
        f'file "{executable_path}"',
        f"attach {pid}",
        "set scheduler-locking on",
    ]
    for index, (library, status_symbol) in enumerate(libraries):
        path = gdb_string(str(library))
        lines.extend(
            [
                f'set $handle{index} = (void *) dlopen("{path}", 258)',
                f'printf "probe_handle_{index}=%p\\n", $handle{index}',
                f"if $handle{index} == 0",
                f'  printf "probe_status_{index}=dlopen_failed\\n"',
                "else",
                f"  set $status{index} = (const char * (*)()) "
                f'dlsym($handle{index}, "{status_symbol}")',
                f'  printf "probe_status_fn_{index}=%p\\n", $status{index}',
                f"  if $status{index} == 0",
                f'    printf "probe_status_{index}=status_symbol_missing\\n"',
                "  else",
                f'    printf "probe_status_{index}=%s\\n", $status{index}()',
                "  end",
                "end",
            ]
        )
    lines.extend(["detach", "quit", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--gdb", default="gdb")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    proc = Path("/proc") / str(args.pid)
    executable_link = proc / "exe"
    if not executable_link.exists():
        raise SystemExit(f"process {args.pid} does not exist")
    executable = executable_link.resolve()
    build_id = elf_build_id(executable)
    if build_id != EXPECTED_BUILD_ID:
        raise SystemExit(
            f"refusing build {build_id}; expected exact build {EXPECTED_BUILD_ID}"
        )

    libraries = [
        ((args.build_dir / filename).resolve(), status_symbol)
        for filename, status_symbol in PROBES
    ]
    missing = [str(path) for path, _ in libraries if not path.is_file()]
    if missing:
        raise SystemExit("missing probe libraries: " + ", ".join(missing))
    maps = (proc / "maps").read_text(encoding="utf-8", errors="replace")
    loaded = [path.name for path, _ in libraries if path.name in maps]
    if loaded:
        raise SystemExit(
            "refusing duplicate process-lifetime probe load: " + ", ".join(loaded)
        )

    script = render_gdb(args.pid, executable, libraries)
    if args.dry_run:
        print(script)
        return 0
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", prefix="iag-passive-probes-", suffix=".gdb", delete=False
    ) as stream:
        stream.write(script)
        script_path = Path(stream.name)
    try:
        result = subprocess.run(
            [args.gdb, "-q", "-batch", "-x", str(script_path)],
            capture_output=True,
            text=True,
        )
    finally:
        script_path.unlink(missing_ok=True)
    output = result.stdout + result.stderr
    print(output, end="")
    statuses = re.findall(r"probe_status_\d+=([^\r\n]+)", output)
    if result.returncode != 0 or len(statuses) != len(PROBES):
        return 2
    if any(not status.startswith("ready:") for status in statuses):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
