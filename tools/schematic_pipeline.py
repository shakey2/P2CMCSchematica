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


def _block_pos(block: dict[str, Any]) -> tuple[int, int, int]:
    pos = block.get("pos", {})
    if isinstance(pos, dict):
        return (int(pos.get("x", 0)), int(pos.get("y", 0)), int(pos.get("z", 0)))
    if isinstance(pos, (list, tuple)) and len(pos) == 3:
        return (int(pos[0]), int(pos[1]), int(pos[2]))
    return (0, 0, 0)


def summarize_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Create a retrieval-oriented summary for a Create IR payload.

    Summary fields are intentionally compact so they can be used as a first-pass
    retrieval layer before injecting full IR examples into prompts.
    """
    blocks = ir.get("blocks", [])
    networks = ir.get("networks", [])

    component_counts: dict[str, int] = {}
    for block in blocks:
        block_id = str(block.get("id", "unknown"))
        component_counts[block_id] = component_counts.get(block_id, 0) + 1

    xs: list[int] = []
    ys: list[int] = []
    zs: list[int] = []
    for block in blocks:
        x, y, z = _block_pos(block)
        xs.append(x)
        ys.append(y)
        zs.append(z)

    if xs:
        dimensions = {
            "x": max(xs) - min(xs) + 1,
            "y": max(ys) - min(ys) + 1,
            "z": max(zs) - min(zs) + 1,
        }
    else:
        dimensions = {"x": 0, "y": 0, "z": 0}

    network_topology = {
        "network_count": len(networks),
        "largest_network_members": max((len(n.get("members", [])) for n in networks), default=0),
        "output_count": len(ir.get("annotations", {}).get("outputs", [])),
    }

    su_values = [float(n.get("su", 0.0)) for n in networks if isinstance(n.get("su"), (int, float))]
    su_production = sum(v for v in su_values if v > 0)
    su_consumption = sum(abs(v) for v in su_values if v < 0)

    stress_stats = {
        "su_production": su_production,
        "su_consumption": su_consumption,
        "net_su": su_production - su_consumption,
    }

    tags: list[str] = []
    volume = dimensions["x"] * dimensions["y"] * dimensions["z"]
    total_blocks = len(blocks)

    if volume and volume <= 125:
        tags.append("compact")
    if su_production >= 4096:
        tags.append("high-SU")
    if total_blocks and total_blocks <= 48:
        tags.append("low-material")
    if su_production > 0 and su_consumption > su_production:
        tags.append("stress-deficit")

    return {
        "dimensions": dimensions,
        "component_counts": dict(sorted(component_counts.items())),
        "network_topology": network_topology,
        "stress": stress_stats,
        "tags": tags,
    }


def build_retrieval_corpus(examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Precompute summaries for each stored schematic/IR example."""
    corpus: list[dict[str, Any]] = []
    for example in examples:
        record_id = str(example.get("id", f"example-{len(corpus)}"))
        ir = dict(example.get("ir", {}))
        summary = summarize_ir(ir)
        corpus.append(
            {
                "id": record_id,
                "summary": summary,
                "ir": ir,
            }
        )
    return corpus


def _retrieval_score(summary: dict[str, Any], query: dict[str, Any]) -> float:
    score = 0.0
    required_tags = set(query.get("required_tags", []))
    summary_tags = set(summary.get("tags", []))
    score += 10.0 * len(required_tags.intersection(summary_tags))

    target_su = query.get("target_su")
    if isinstance(target_su, (int, float)):
        delta = abs(float(target_su) - float(summary.get("stress", {}).get("su_production", 0.0)))
        score += max(0.0, 5.0 - (delta / 1024.0))

    max_dimensions = query.get("max_dimensions")
    if isinstance(max_dimensions, dict):
        dims = summary.get("dimensions", {})
        fits = (
            int(dims.get("x", 0)) <= int(max_dimensions.get("x", 0))
            and int(dims.get("y", 0)) <= int(max_dimensions.get("y", 0))
            and int(dims.get("z", 0)) <= int(max_dimensions.get("z", 0))
        )
        if fits:
            score += 3.0

    return score


def retrieval_first_prompt_context(
    query: dict[str, Any],
    corpus: list[dict[str, Any]],
    *,
    top_k: int = 5,
    include_full_ir: int = 1,
) -> dict[str, Any]:
    """Build prompt context with summaries first and selective full IR payloads.

    This supports a retrieval-first strategy where most context budget is spent
    on compact summaries and only the strongest matches include full examples.
    """
    ranked = sorted(
        corpus,
        key=lambda record: _retrieval_score(record.get("summary", {}), query),
        reverse=True,
    )
    selected = ranked[: max(0, top_k)]

    summaries = [{"id": rec["id"], "summary": rec["summary"]} for rec in selected]
    full_ir_examples = [
        {"id": rec["id"], "ir": rec["ir"]}
        for rec in selected[: max(0, min(include_full_ir, len(selected)))]
    ]

    return {
        "query": query,
        "retrieved_summaries": summaries,
        "full_ir_examples": full_ir_examples,
    }
