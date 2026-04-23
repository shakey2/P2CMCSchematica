#!/usr/bin/env python3
"""Decompile/compile helpers for Create-oriented schematic payloads.

The decompiled representation is JSON-friendly and stable for round-trips.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rule_pack import load_rule_pack

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


def _retrieval_reason(summary: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    """Explain why an example matched a retrieval query."""
    reasons: list[str] = []
    required_tags = set(query.get("required_tags", []))
    summary_tags = set(summary.get("tags", []))
    matched_tags = sorted(required_tags.intersection(summary_tags))
    if matched_tags:
        reasons.append(f"matched tags: {', '.join(matched_tags)}")

    target_su = query.get("target_su")
    if isinstance(target_su, (int, float)):
        produced = float(summary.get("stress", {}).get("su_production", 0.0))
        reasons.append(f"su delta={abs(float(target_su) - produced):.1f}")

    max_dimensions = query.get("max_dimensions")
    if isinstance(max_dimensions, dict):
        dims = summary.get("dimensions", {})
        fits = (
            int(dims.get("x", 0)) <= int(max_dimensions.get("x", 0))
            and int(dims.get("y", 0)) <= int(max_dimensions.get("y", 0))
            and int(dims.get("z", 0)) <= int(max_dimensions.get("z", 0))
        )
        reasons.append("fits size bound" if fits else "exceeds size bound")

    if not reasons:
        reasons.append("general similarity")

    return {
        "score": _retrieval_score(summary, query),
        "why_this_example": reasons,
    }


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

    summaries = [
        {
            "id": rec["id"],
            "summary": rec["summary"],
            "retrieval_trace": _retrieval_reason(rec.get("summary", {}), query),
        }
        for rec in selected
    ]
    full_ir_examples = [
        {"id": rec["id"], "ir": rec["ir"]}
        for rec in selected[: max(0, min(include_full_ir, len(selected)))]
    ]

    return {
        "query": query,
        "retrieved_summaries": summaries,
        "full_ir_examples": full_ir_examples,
    }


def parse_user_intent(intent: dict[str, Any]) -> dict[str, Any]:
    """Normalize user intent into retrieval and policy fields for planning."""
    size = intent.get("size", {})
    compactness = str(intent.get("compactness", "balanced")).strip().lower()
    exploit_tolerance = str(intent.get("exploit_tolerance", "safe")).strip().lower()

    normalized = {
        "target_su": float(intent.get("su", 0.0)) if isinstance(intent.get("su"), (int, float)) else 0.0,
        "max_dimensions": {
            "x": int(size.get("x", 0)) if isinstance(size, dict) else 0,
            "y": int(size.get("y", 0)) if isinstance(size, dict) else 0,
            "z": int(size.get("z", 0)) if isinstance(size, dict) else 0,
        },
        "compactness": compactness,
        "exploit_tolerance": exploit_tolerance,
        "required_tags": [],
    }

    if compactness in {"compact", "high", "strict"}:
        normalized["required_tags"].append("compact")
    if normalized["target_su"] >= 4096:
        normalized["required_tags"].append("high-SU")
    return normalized


def select_relevant_mechanic_sections(
    rule_pack: dict[str, Any], parsed_intent: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Select rule-pack slices used to guide planning and generation."""
    policy = parsed_intent.get("exploit_tolerance", "safe")
    selected: dict[str, Any] = {
        "supported_blocks": rule_pack.get("supported_blocks", {}),
        "kinetic_rules": {
            "rpm_limits_by_block": rule_pack.get("kinetic_rules", {}).get("rpm_limits_by_block", {}),
            "stress_limits_by_block": rule_pack.get("kinetic_rules", {}).get(
                "stress_limits_by_block", {}
            ),
            "connectivity": rule_pack.get("kinetic_rules", {}).get("connectivity", {}),
        },
    }
    trace: list[dict[str, str]] = [
        {
            "section": "kinetic_rules.rpm_limits_by_block",
            "why_this_rule": "SU planning needs per-block RPM ceilings.",
        },
        {
            "section": "kinetic_rules.stress_limits_by_block",
            "why_this_rule": "SU planning needs stress-unit caps by block.",
        },
    ]

    if policy == "safe":
        selected["vanilla_mechanics"] = rule_pack.get("vanilla_mechanics", {})
        selected["incompatibilities"] = rule_pack.get("incompatibilities", {})
        trace.extend(
            [
                {
                    "section": "vanilla_mechanics",
                    "why_this_rule": "Safe policy enforces vanilla interaction behavior.",
                },
                {
                    "section": "incompatibilities",
                    "why_this_rule": "Safe policy avoids known unstable patterns.",
                },
            ]
        )
    elif policy == "quirks":
        selected["incompatibilities"] = {
            "banned_patterns": rule_pack.get("incompatibilities", {}).get("banned_patterns", [])
        }
        trace.append(
            {
                "section": "incompatibilities.banned_patterns",
                "why_this_rule": "Quirks policy allows edge cases but keeps hard bans.",
            }
        )

    return selected, trace


def build_planner_prompt_context(
    request: dict[str, Any],
    examples: list[dict[str, Any]],
    *,
    top_k: int = 5,
    include_full_ir: int = 1,
) -> dict[str, Any]:
    """Planner pipeline for intent->rules->retrieval->focused prompt package."""
    parsed_intent = parse_user_intent(dict(request.get("intent", {})))
    env = dict(request.get("environment", {}))
    rule_pack = load_rule_pack(
        str(env.get("loader", "")),
        str(env.get("minecraft_version", "")),
        str(env.get("create_version", "")),
    )
    selected_rules, rule_trace = select_relevant_mechanic_sections(rule_pack, parsed_intent)

    corpus = build_retrieval_corpus(examples)
    retrieval_context = retrieval_first_prompt_context(
        {
            "required_tags": parsed_intent.get("required_tags", []),
            "target_su": parsed_intent.get("target_su", 0.0),
            "max_dimensions": parsed_intent.get("max_dimensions", {}),
        },
        corpus,
        top_k=top_k,
        include_full_ir=include_full_ir,
    )

    example_trace = [
        {
            "id": rec["id"],
            "why_this_example": rec.get("retrieval_trace", {}).get("why_this_example", []),
            "score": rec.get("retrieval_trace", {}).get("score", 0.0),
        }
        for rec in retrieval_context.get("retrieved_summaries", [])
    ]

    return {
        "parsed_intent": parsed_intent,
        "environment": env,
        "selected_rules": selected_rules,
        "retrieval": retrieval_context,
        "prompt_package": {
            "intent": parsed_intent,
            "rules": selected_rules,
            "retrieved_summaries": retrieval_context.get("retrieved_summaries", []),
            "full_ir_examples": retrieval_context.get("full_ir_examples", []),
        },
        "planner_trace": {
            "why_this_rule": rule_trace,
            "why_this_example": example_trace,
        },
    }
