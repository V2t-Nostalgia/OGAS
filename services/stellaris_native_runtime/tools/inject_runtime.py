#!/usr/bin/env python3
"""Load the exact-build production runtime into one running Stellaris process."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_STATUS_SYMBOL = "iag_native_runtime_status"
SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    SERVICE_ROOT
    / "versions"
    / "manifests"
    / "stellaris_4_5_2_linux.json"
)
VERIFY_BINARY = SERVICE_ROOT / "tools" / "version_profile" / "verify_binary.py"


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


def render_gdb(pid: int, executable: Path, library: Path) -> str:
    executable_path = gdb_string(str(executable))
    library_path = gdb_string(str(library))
    return "\n".join(
        (
            "set pagination off",
            "set confirm off",
            f'file "{executable_path}"',
            f"attach {pid}",
            "set scheduler-locking on",
            f'set $handle = (void *) dlopen("{library_path}", 258)',
            'printf "runtime_handle=%p\\n", $handle',
            "if $handle == 0",
            '  printf "runtime_status=dlopen_failed\\n"',
            "else",
            (
                "  set $status = (const char * (*)()) "
                f'dlsym($handle, "{RUNTIME_STATUS_SYMBOL}")'
            ),
            '  printf "runtime_status_fn=%p\\n", $status',
            "  if $status == 0",
            '    printf "runtime_status=status_symbol_missing\\n"',
            "  else",
            '    printf "runtime_status=%s\\n", $status()',
            "  end",
            "end",
            "detach",
            "quit",
            "",
        )
    )


def verify_exact_binary(manifest_path: Path, executable: Path) -> str:
    """Run the shared exact-binary verifier and return the expected Build ID."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["platform"] != "linux-x86_64":
            raise ValueError("manifest platform is not linux-x86_64")
        expected_build_id = str(manifest["binary"]["elf_build_id"]).lower()
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid exact-build manifest {manifest_path}: {error}") from error
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFY_BINARY),
            "--manifest",
            str(manifest_path),
            "--binary",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()
        raise SystemExit(f"exact-build preflight failed:\n{detail}")
    return expected_build_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--gdb", default="gdb")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    process = Path("/proc") / str(args.pid)
    executable_link = process / "exe"
    if not executable_link.exists():
        raise SystemExit(f"process {args.pid} does not exist")
    executable = executable_link.resolve()
    expected_build_id = verify_exact_binary(args.manifest.resolve(), executable)
    build_id = elf_build_id(executable)
    if build_id != expected_build_id:
        raise SystemExit(
            f"refusing build {build_id}; expected exact build {expected_build_id}"
        )

    library = args.library.resolve()
    if not library.is_file():
        raise SystemExit(f"runtime library does not exist: {library}")
    maps = (process / "maps").read_text(encoding="utf-8", errors="replace")
    if str(library) in maps or library.name in maps:
        raise SystemExit(f"refusing duplicate process-lifetime load: {library.name}")

    script = render_gdb(args.pid, executable, library)
    if args.dry_run:
        print(script)
        return 0
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", prefix="iag-native-runtime-", suffix=".gdb", delete=False
    ) as stream:
        stream.write(script)
        script_path = Path(stream.name)
    try:
        result = subprocess.run(
            [args.gdb, "-q", "-batch", "-x", str(script_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    finally:
        script_path.unlink(missing_ok=True)
    output = result.stdout + result.stderr
    print(output, end="")
    match = re.search(r"^runtime_status=([^\r\n]+)$", output, re.MULTILINE)
    if result.returncode != 0 or match is None:
        return 2
    return 0 if match.group(1) == "ready" else 3


if __name__ == "__main__":
    raise SystemExit(main())
