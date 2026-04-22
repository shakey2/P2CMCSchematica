#!/usr/bin/env python3
"""Decompile/compile helpers for Create-oriented schematic payloads.

The decompiled representation is JSON-friendly and stable for round-trips.
"""

from __future__ import annotations

from typing import Any

CREATE_BLOCK_ENTITY_FIELD_WHITELIST: dict[str, set[str]] = {
    "create:kinetic_block_entity": {
        "id",
        "Speed",
        "ForceAngle",
        "GeneratedSpeed",
        "IsGenerator",
        "SequencedOffsetLimit",
        "network",
        "source",
    },
    "create:belt_block_entity": {
        "id",
        "Length",
        "Controller",
        "Index",
        "Direction",
        "IsController",
        "Passengers",
        "Inventory",
    },
    "create:smart_chute": {
        "id",
        "Filter",
        "ExtractionCount",
        "Powered",
    },
    "create:depot": {
        "id",
        "HeldItem",
        "ProcessingTime",
        "OutputBuffer",
    },
    "create:portable_storage_interface": {
        "id",
        "Distance",
        "TransferTimer",
        "Connected",
    },
}


def _position_key(pos: list[int] | tuple[int, int, int]) -> str:
    return f"{int(pos[0])},{int(pos[1])},{int(pos[2])}"


def _parse_position_key(position_key: str) -> list[int]:
    x, y, z = position_key.split(",")
    return [int(x), int(y), int(z)]


def _sanitize_block_entity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    entity_id = payload.get("id")
    if not isinstance(entity_id, str):
        return dict(payload)

    allowed_fields = CREATE_BLOCK_ENTITY_FIELD_WHITELIST.get(entity_id)
    if not allowed_fields:
        return dict(payload)

    return {key: value for key, value in payload.items() if key in allowed_fields}


def decompile_schematic(schematic: dict[str, Any]) -> dict[str, Any]:
    """Extract a stable intermediate representation from a schematic-like dict."""
    palette = schematic.get("palette", [])
    blocks_ir: list[dict[str, Any]] = []
    block_entities: dict[str, dict[str, Any]] = {}

    for block in schematic.get("blocks", []):
        pos = [int(block["pos"][0]), int(block["pos"][1]), int(block["pos"][2])]
        state_idx = int(block["state"])
        palette_entry = palette[state_idx]

        block_ir = {
            "pos": pos,
            "id": palette_entry["Name"],
            "properties": dict(palette_entry.get("Properties", {})),
        }
        blocks_ir.append(block_ir)

        if isinstance(block.get("nbt"), dict):
            block_entities[_position_key(pos)] = _sanitize_block_entity_payload(block["nbt"])

    blocks_ir.sort(key=lambda b: (b["pos"][0], b["pos"][1], b["pos"][2]))

    return {
        "size": list(schematic.get("size", [])),
        "blocks": blocks_ir,
        "block_entities": block_entities,
        "entities": list(schematic.get("entities", [])),
        "metadata": {
            key: value
            for key, value in schematic.items()
            if key not in {"size", "palette", "blocks", "entities"}
        },
    }


def compile_schematic(ir: dict[str, Any]) -> dict[str, Any]:
    """Compile decompiled IR back into schematic-like dict.

    The palette order is generated from first appearance in the sorted block list
    for deterministic round-trips.
    """
    palette: list[dict[str, Any]] = []
    palette_index: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
    blocks_out: list[dict[str, Any]] = []

    sorted_blocks = sorted(
        ir.get("blocks", []), key=lambda b: (b["pos"][0], b["pos"][1], b["pos"][2])
    )

    for block in sorted_blocks:
        block_id = block["id"]
        properties = dict(block.get("properties", {}))
        palette_key = (block_id, tuple(sorted(properties.items())))

        if palette_key not in palette_index:
            palette_index[palette_key] = len(palette)
            entry: dict[str, Any] = {"Name": block_id}
            if properties:
                entry["Properties"] = properties
            palette.append(entry)

        pos = [int(block["pos"][0]), int(block["pos"][1]), int(block["pos"][2])]
        block_out: dict[str, Any] = {
            "pos": pos,
            "state": palette_index[palette_key],
        }

        pos_key = _position_key(pos)
        payload = ir.get("block_entities", {}).get(pos_key)
        if isinstance(payload, dict):
            block_out["nbt"] = _sanitize_block_entity_payload(payload)

        blocks_out.append(block_out)

    schematic: dict[str, Any] = {
        "size": list(ir.get("size", [])),
        "palette": palette,
        "blocks": blocks_out,
        "entities": list(ir.get("entities", [])),
    }
    schematic.update(dict(ir.get("metadata", {})))
    return schematic


def normalize_roundtrip(ir: dict[str, Any]) -> dict[str, Any]:
    """Normalize via compile->decompile to compare equivalence deterministically."""
    return decompile_schematic(compile_schematic(ir))
