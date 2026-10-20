#!/usr/bin/env python3
"""Send one bounded request to a locally loaded Stellaris native runtime."""

from __future__ import annotations

import argparse
import socket
from pathlib import Path


MAX_RESPONSE_BYTES = 65_536


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action")
    parser.add_argument("country_id", type=int)
    parser.add_argument("fields", nargs="*")
    parser.add_argument("--request-id", required=True)
    parser.add_argument(
        "--socket", type=Path, default=Path("/tmp/iag-stellaris-native.sock")
    )
    args = parser.parse_args(argv)

    tokens = ("IAG1", args.request_id, args.action, str(args.country_id), *args.fields)
    if any("\t" in item or "\n" in item for item in tokens):
        raise SystemExit("protocol fields may not contain tabs or newlines")
    request = ("\t".join(tokens) + "\n").encode("utf-8")

    payload = bytearray()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(25.0)
        connection.connect(str(args.socket))
        connection.sendall(request)
        while len(payload) <= MAX_RESPONSE_BYTES:
            chunk = connection.recv(4096)
            if not chunk:
                break
            payload.extend(chunk)
            if b"\n" in chunk:
                break
    if not payload.endswith(b"\n"):
        raise SystemExit("runtime returned an incomplete response")
    if len(payload) > MAX_RESPONSE_BYTES:
        raise SystemExit("runtime response exceeded the size limit")
    print(payload.decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
