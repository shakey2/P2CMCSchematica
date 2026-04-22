#!/usr/bin/env python3
"""Probe Minecraft NBT files and print key paths/types.

Supports gzip-compressed and uncompressed NBT files.
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import struct
from dataclasses import dataclass
from typing import Any, BinaryIO

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

TAG_NAMES = {
    TAG_END: "end",
    TAG_BYTE: "byte",
    TAG_SHORT: "short",
    TAG_INT: "int",
    TAG_LONG: "long",
    TAG_FLOAT: "float",
    TAG_DOUBLE: "double",
    TAG_BYTE_ARRAY: "byte_array",
    TAG_STRING: "string",
    TAG_LIST: "list",
    TAG_COMPOUND: "compound",
    TAG_INT_ARRAY: "int_array",
    TAG_LONG_ARRAY: "long_array",
}


class NBTDecodeError(RuntimeError):
    pass


@dataclass
class ListValue:
    element_tag: int
    values: list[Any]


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    data = stream.read(n)
    if len(data) != n:
        raise NBTDecodeError(f"Unexpected EOF: needed {n} bytes, got {len(data)}")
    return data


def _read_u8(stream: BinaryIO) -> int:
    return struct.unpack(">B", _read_exact(stream, 1))[0]


def _read_i16(stream: BinaryIO) -> int:
    return struct.unpack(">h", _read_exact(stream, 2))[0]


def _read_i32(stream: BinaryIO) -> int:
    return struct.unpack(">i", _read_exact(stream, 4))[0]


def _read_i64(stream: BinaryIO) -> int:
    return struct.unpack(">q", _read_exact(stream, 8))[0]


def _read_f32(stream: BinaryIO) -> float:
    return struct.unpack(">f", _read_exact(stream, 4))[0]


def _read_f64(stream: BinaryIO) -> float:
    return struct.unpack(">d", _read_exact(stream, 8))[0]


def _read_string(stream: BinaryIO) -> str:
    n = struct.unpack(">H", _read_exact(stream, 2))[0]
    return _read_exact(stream, n).decode("utf-8")


def _read_payload(stream: BinaryIO, tag_type: int) -> Any:
    if tag_type == TAG_BYTE:
        return struct.unpack(">b", _read_exact(stream, 1))[0]
    if tag_type == TAG_SHORT:
        return _read_i16(stream)
    if tag_type == TAG_INT:
        return _read_i32(stream)
    if tag_type == TAG_LONG:
        return _read_i64(stream)
    if tag_type == TAG_FLOAT:
        return _read_f32(stream)
    if tag_type == TAG_DOUBLE:
        return _read_f64(stream)
    if tag_type == TAG_BYTE_ARRAY:
        n = _read_i32(stream)
        return _read_exact(stream, n)
    if tag_type == TAG_STRING:
        return _read_string(stream)
    if tag_type == TAG_LIST:
        elem_tag = _read_u8(stream)
        n = _read_i32(stream)
        values = [_read_payload(stream, elem_tag) for _ in range(n)]
        return ListValue(elem_tag, values)
    if tag_type == TAG_COMPOUND:
        result: dict[str, Any] = {}
        while True:
            inner_tag = _read_u8(stream)
            if inner_tag == TAG_END:
                break
            name = _read_string(stream)
            result[name] = _read_payload(stream, inner_tag)
        return result
    if tag_type == TAG_INT_ARRAY:
        n = _read_i32(stream)
        return [_read_i32(stream) for _ in range(n)]
    if tag_type == TAG_LONG_ARRAY:
        n = _read_i32(stream)
        return [_read_i64(stream) for _ in range(n)]
    raise NBTDecodeError(f"Unsupported tag type {tag_type}")


def load_nbt(path: str) -> tuple[str, Any]:
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        payload = gzip.decompress(raw)
    else:
        payload = raw

    stream = io.BytesIO(payload)
    root_tag = _read_u8(stream)
    if root_tag != TAG_COMPOUND:
        raise NBTDecodeError(f"Root tag must be compound (10), got {root_tag}")
    root_name = _read_string(stream)
    root_payload = _read_payload(stream, root_tag)
    return root_name, root_payload


def scalar_type_name(value: Any) -> str:
    if isinstance(value, bytes):
        return "byte_array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, float):
        return "double_or_float"
    if isinstance(value, int):
        return "int_like"
    if isinstance(value, list):
        if value and all(isinstance(x, int) for x in value):
            return "int_array_or_long_array"
        return "list"
    return type(value).__name__


def walk(path: str, value: Any, out: list[str]) -> None:
    if isinstance(value, dict):
        out.append(f"{path}: compound[{len(value)}]")
        for key in sorted(value):
            walk(f"{path}.{key}", value[key], out)
        return

    if isinstance(value, ListValue):
        tag_name = TAG_NAMES.get(value.element_tag, str(value.element_tag))
        out.append(f"{path}: list<{tag_name}>[{len(value.values)}]")

        # Show at most first three entries to keep output compact.
        for idx, item in enumerate(value.values[:3]):
            walk(f"{path}[{idx}]", item, out)
        if len(value.values) > 3:
            out.append(f"{path}[...]: +{len(value.values) - 3} more")
        return

    out.append(f"{path}: {scalar_type_name(value)}")


def probe_file(path: str) -> str:
    root_name, root = load_nbt(path)
    lines = [f"# {path}", f"root_name: {root_name!r}"]
    walk("root", root, lines)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Print key paths/types in NBT files")
    parser.add_argument("paths", nargs="+", help=".nbt files or directories")
    args = parser.parse_args()

    files: list[str] = []
    for p in args.paths:
        if os.path.isdir(p):
            for name in sorted(os.listdir(p)):
                if name.lower().endswith(".nbt"):
                    files.append(os.path.join(p, name))
        else:
            files.append(p)

    if not files:
        raise SystemExit("No .nbt files found")

    for i, path in enumerate(files):
        print(probe_file(path))
        if i != len(files) - 1:
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
