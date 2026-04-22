#!/usr/bin/env python3
"""Materialize text-encoded Create sample NBTs into binary .nbt files.

This avoids committing raw binary blobs while still providing reproducible `.nbt`
fixtures for probing.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Decode *.nbt.b64 fixtures into *.nbt")
    parser.add_argument(
        "src_dir",
        nargs="?",
        default="samples/create_exports",
        help="Directory containing .nbt.b64 fixture files",
    )
    parser.add_argument(
        "out_dir",
        nargs="?",
        default=".tmp/create_exports",
        help="Output directory for decoded .nbt files",
    )
    args = parser.parse_args()

    src_dir = Path(args.src_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(src_dir.glob("*.nbt.b64"))
    if not files:
        raise SystemExit(f"No .nbt.b64 files found in {src_dir}")

    for src in files:
        raw = base64.b64decode(src.read_text())
        out_name = src.name[: -len(".b64")]
        out_path = out_dir / out_name
        out_path.write_bytes(raw)
        print(f"wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
