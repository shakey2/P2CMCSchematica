#!/usr/bin/env python3
"""Validate Create IR JSON before compilation.

Usage:
  python tools/validate_create_ir.py path/to/ir.json

Notes:
  - Do not wrap the path in angle brackets when running in a shell.
    ✅ python tools/validate_create_ir.py ./tmp_ir.json
    ❌ python tools/validate_create_ir.py <tmp_ir.json>
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rule_pack import RulePackError, load_rule_pack, machine_rule_views

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install with `pip install jsonschema`."
    ) from exc


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "create_ir.schema.json"
REQUEST_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "generation_request.schema.json"
)


class IRValidationError(ValueError):
    """Raised when AI output is malformed and must be rejected."""


@dataclass(frozen=True)
class MachineDiagnostic:
    code: str
    message: str
    block_pos: dict[str, int] | None
    suggested_fix: str


DEFAULT_ORIENTATION_REQUIRED_BY_BLOCK: dict[str, set[str]] = {
    "create:shaft": {"axis"},
    "create:cogwheel": {"axis"},
    "create:large_cogwheel": {"axis"},
    "create:gearbox": {"axis"},
    "create:clutch": {"axis"},
    "create:gearshift": {"axis"},
    "create:encased_chain_drive": {"axis"},
}

DEFAULT_MECHANICAL_BLOCK_IDS: set[str] = {
    "create:shaft",
    "create:cogwheel",
    "create:large_cogwheel",
    "create:gearbox",
    "create:clutch",
    "create:gearshift",
    "create:encased_chain_drive",
    "create:mechanical_belt",
}

DEFAULT_RPM_LIMITS_BY_BLOCK: dict[str, float] = {
    "create:shaft": 256.0,
    "create:cogwheel": 256.0,
    "create:large_cogwheel": 128.0,
    "create:gearbox": 128.0,
    "create:clutch": 128.0,
    "create:gearshift": 128.0,
    "create:encased_chain_drive": 96.0,
    "create:mechanical_belt": 64.0,
}

DEFAULT_SU_LIMITS_BY_BLOCK: dict[str, float] = {
    "create:shaft": 16384.0,
    "create:cogwheel": 16384.0,
    "create:large_cogwheel": 8192.0,
    "create:gearbox": 4096.0,
    "create:clutch": 4096.0,
    "create:gearshift": 4096.0,
    "create:encased_chain_drive": 2048.0,
    "create:mechanical_belt": 1024.0,
}

DEFAULT_SUPPORTED_ENTITY_BY_BLOCK: dict[str, set[str]] = {
    "create:shaft": {"create:kinetic_block_entity"},
    "create:cogwheel": {"create:kinetic_block_entity"},
    "create:large_cogwheel": {"create:kinetic_block_entity"},
    "create:gearbox": {"create:kinetic_block_entity"},
    "create:clutch": {"create:kinetic_block_entity"},
    "create:gearshift": {"create:kinetic_block_entity"},
    "create:encased_chain_drive": {"create:kinetic_block_entity"},
    "create:mechanical_belt": {"create:belt_block_entity"},
}


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_request_schema() -> dict[str, Any]:
    with REQUEST_SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_generation_request_or_raise(request: dict[str, Any]) -> None:
    """Validate upstream request context before attempting generation."""
    schema = _load_request_schema()
    validator = jsonschema.Draft202012Validator(schema)
    structural_errors = sorted(validator.iter_errors(request), key=lambda e: list(e.path))
    if structural_errors:
        formatted = "\n".join(
            f"- {'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in structural_errors
        )
        raise IRValidationError(f"Generation request validation failed:\n{formatted}")

    fingerprint = str(request.get("fingerprint", "")).strip()
    if not fingerprint:
        raise IRValidationError(
            "Generation request validation failed:\n"
            "- fingerprint: missing or blank fingerprint is not allowed"
        )

    installed_mods = request.get("installed_mods", [])
    if not isinstance(installed_mods, list):
        return

    seen_ids: set[str] = set()
    ambiguous_ids: set[str] = set()
    for mod in installed_mods:
        if not isinstance(mod, dict):
            continue
        mod_id = str(mod.get("id", "")).strip()
        mod_version = str(mod.get("version", "")).strip()
        if mod_id in seen_ids:
            ambiguous_ids.add(mod_id)
        seen_ids.add(mod_id)
        if mod_version in {"*", "latest", "any", "unknown"}:
            ambiguous_ids.add(mod_id or "<empty-id>")

    if ambiguous_ids:
        ids = ", ".join(sorted(ambiguous_ids))
        raise IRValidationError(
            "Generation request validation failed:\n"
            f"- installed_mods: ambiguous mod fingerprint for ids [{ids}]"
        )

    try:
        load_rule_pack(
            str(request.get("loader", "")),
            str(request.get("minecraft_version", "")),
            str(request.get("create_version", "")),
        )
    except RulePackError as exc:
        raise IRValidationError(f"Generation request validation failed:\n- rules: {exc}") from exc


def _check_semantics(ir: dict[str, Any]) -> list[str]:
    """Additional checks that are harder to encode in portable JSON schema."""
    errors: list[str] = []

    # Constraint semantics: rpm_range min must be <= max.
    for i, constraint in enumerate(ir.get("constraints", [])):
        if constraint.get("type") == "rpm_range":
            min_rpm = constraint.get("min")
            max_rpm = constraint.get("max")
            if min_rpm is not None and max_rpm is not None and min_rpm > max_rpm:
                errors.append(
                    f"constraints[{i}]: rpm_range min ({min_rpm}) must be <= max ({max_rpm})"
                )

    # Position uniqueness for blocks to avoid overlapping writes during compilation.
    seen_positions: set[tuple[int, int, int]] = set()
    for i, block in enumerate(ir.get("blocks", [])):
        pos = block["pos"]
        key = (pos["x"], pos["y"], pos["z"])
        if key in seen_positions:
            errors.append(f"blocks[{i}]: duplicate block position {key}")
        seen_positions.add(key)

    # Output annotation must refer to declared network ids.
    network_ids = {network["id"] for network in ir.get("networks", [])}
    for i, output in enumerate(ir.get("annotations", {}).get("outputs", [])):
        target_network_id = output["target_network_id"]
        if target_network_id not in network_ids:
            errors.append(
                "annotations.outputs"
                f"[{i}]: target_network_id '{target_network_id}' not found in networks[]"
            )

    return errors


def _matching_suffix_map(
    rules: dict[str, Any], block_id: str
) -> tuple[str, Any] | None:
    for key, value in rules.items():
        if block_id == key or block_id.endswith(key):
            return key, value
    return None


def _resolve_machine_rules(rule_pack: dict[str, Any] | None) -> dict[str, Any]:
    if rule_pack is None:
        return {
            "mechanical_block_ids": DEFAULT_MECHANICAL_BLOCK_IDS,
            "orientation_required_by_block": DEFAULT_ORIENTATION_REQUIRED_BY_BLOCK,
            "rpm_limits_by_block": DEFAULT_RPM_LIMITS_BY_BLOCK,
            "stress_limits_by_block": DEFAULT_SU_LIMITS_BY_BLOCK,
            "supported_entity_by_block": DEFAULT_SUPPORTED_ENTITY_BY_BLOCK,
            "connectivity_required": True,
            "banned_patterns": [],
        }
    return machine_rule_views(rule_pack)


def validate_create_machine(
    ir: dict[str, Any], rule_pack: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run Create-specific semantic checks and return structured diagnostics."""
    machine_rules = _resolve_machine_rules(rule_pack)
    orientation_required_by_block = machine_rules["orientation_required_by_block"]
    mechanical_block_ids = machine_rules["mechanical_block_ids"]
    rpm_limits_by_block = machine_rules["rpm_limits_by_block"]
    stress_limits_by_block = machine_rules["stress_limits_by_block"]
    supported_entity_by_block = machine_rules["supported_entity_by_block"]
    connectivity_required = machine_rules["connectivity_required"]
    banned_patterns = machine_rules["banned_patterns"]

    diagnostics: list[MachineDiagnostic] = []
    blocks = ir.get("blocks", [])
    networks = ir.get("networks", [])
    constraints = ir.get("constraints", [])

    block_by_pos: dict[tuple[int, int, int], dict[str, Any]] = {}
    for block in blocks:
        pos = block["pos"]
        block_by_pos[(pos["x"], pos["y"], pos["z"])] = block

    # Bounding box constraints from constraints[type=dimensions].
    if blocks:
        xs = [b["pos"]["x"] for b in blocks]
        ys = [b["pos"]["y"] for b in blocks]
        zs = [b["pos"]["z"] for b in blocks]
        span = {
            "x": max(xs) - min(xs) + 1,
            "y": max(ys) - min(ys) + 1,
            "z": max(zs) - min(zs) + 1,
        }
        for constraint in constraints:
            if constraint.get("type") != "dimensions":
                continue
            max_dims = constraint["max"]
            for axis in ("x", "y", "z"):
                if span[axis] > max_dims[axis]:
                    diagnostics.append(
                        MachineDiagnostic(
                            code="bbox.exceeds_constraint",
                            message=(
                                f"Machine span on {axis}-axis is {span[axis]}, "
                                f"which exceeds allowed max {max_dims[axis]}."
                            ),
                            block_pos=None,
                            suggested_fix=(
                                f"Reduce machine extent on {axis}-axis to <= {max_dims[axis]} "
                                "or relax the dimensions constraint."
                            ),
                        )
                    )

    # Per-block checks.
    block_pos_to_network: dict[tuple[int, int, int], str] = {}
    for network in networks:
        network_id = network["id"]
        for member in network["members"]:
            pos_key = (member["x"], member["y"], member["z"])
            if pos_key in block_pos_to_network and block_pos_to_network[pos_key] != network_id:
                diagnostics.append(
                    MachineDiagnostic(
                        code="mechanical.member_in_multiple_networks",
                        message=(
                            f"Block position {pos_key} appears in networks "
                            f"'{block_pos_to_network[pos_key]}' and '{network_id}'."
                        ),
                        block_pos={"x": pos_key[0], "y": pos_key[1], "z": pos_key[2]},
                        suggested_fix="Ensure each mechanical block belongs to exactly one network.",
                    )
                )
            block_pos_to_network[pos_key] = network_id
            if pos_key not in block_by_pos:
                diagnostics.append(
                    MachineDiagnostic(
                        code="mechanical.member_missing_block",
                        message=f"Network '{network_id}' references missing block at {pos_key}.",
                        block_pos={"x": pos_key[0], "y": pos_key[1], "z": pos_key[2]},
                        suggested_fix="Add the missing block or remove this member from the network.",
                    )
                )

    for block in blocks:
        block_id = block["id"]
        pos = block["pos"]
        pos_key = (pos["x"], pos["y"], pos["z"])
        props = block.get("properties", {})

        orientation_rule = _matching_suffix_map(orientation_required_by_block, block_id)
        if orientation_rule:
            _, required_props = orientation_rule
            missing = sorted(p for p in required_props if p not in props)
            if missing:
                diagnostics.append(
                    MachineDiagnostic(
                        code="orientation.missing_property",
                        message=(
                            f"Block '{block_id}' at {pos_key} is missing required orientation "
                            f"properties: {', '.join(missing)}."
                        ),
                        block_pos=pos,
                        suggested_fix=(
                            "Set the required block-state orientation property/properties "
                            "before compilation."
                        ),
                    )
                )

        if _matching_suffix_map({k: None for k in mechanical_block_ids}, block_id) and pos_key not in block_pos_to_network:
            diagnostics.append(
                MachineDiagnostic(
                    code="mechanical.block_not_in_network",
                    message=f"Mechanical block '{block_id}' at {pos_key} is not assigned to any network.",
                    block_pos=pos,
                    suggested_fix="Add this block position to the correct networks[].members list.",
                )
            )

        entity_id = (
            props.get("entity")
            or props.get("entity_id")
            or props.get("block_entity")
            or props.get("block_entity_id")
        )
        if isinstance(entity_id, str):
            entity_rule = _matching_suffix_map(supported_entity_by_block, block_id)
            if entity_rule:
                _, supported_entities = entity_rule
                if entity_id not in supported_entities:
                    diagnostics.append(
                        MachineDiagnostic(
                            code="compat.unsupported_block_entity",
                            message=(
                                f"Block '{block_id}' at {pos_key} cannot use entity '{entity_id}'. "
                                f"Supported: {sorted(supported_entities)}."
                            ),
                            block_pos=pos,
                            suggested_fix="Use a supported block entity id for this block type.",
                        )
                    )

    # Connectivity consistency and RPM/SU rules per network.
    orthogonal_offsets = (
        (1, 0, 0),
        (-1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),
        (0, 0, -1),
    )
    for network in networks:
        member_keys = {(m["x"], m["y"], m["z"]) for m in network["members"]}
        if connectivity_required and len(member_keys) > 1:
            seed = next(iter(member_keys))
            stack = [seed]
            visited = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                for dx, dy, dz in orthogonal_offsets:
                    nxt = (current[0] + dx, current[1] + dy, current[2] + dz)
                    if nxt in member_keys and nxt not in visited:
                        stack.append(nxt)
            if visited != member_keys:
                disconnected = sorted(member_keys - visited)
                bad = disconnected[0]
                diagnostics.append(
                    MachineDiagnostic(
                        code="mechanical.network_disconnected",
                        message=(
                            f"Network '{network['id']}' is mechanically disconnected; "
                            f"example orphan member: {bad}."
                        ),
                        block_pos={"x": bad[0], "y": bad[1], "z": bad[2]},
                        suggested_fix=(
                            "Add bridging transmission components or split disconnected members "
                            "into separate networks."
                        ),
                    )
                )

        if "rpm" in network:
            rpm = float(network["rpm"])
            for pos_key in member_keys:
                block = block_by_pos.get(pos_key)
                if not block:
                    continue
                rpm_rule = _matching_suffix_map(rpm_limits_by_block, block["id"])
                if rpm_rule and abs(rpm) > rpm_rule[1]:
                    diagnostics.append(
                        MachineDiagnostic(
                            code="rpm.exceeds_block_limit",
                            message=(
                                f"Network '{network['id']}' rpm {rpm} exceeds max {rpm_rule[1]} "
                                f"for block '{block['id']}' at {pos_key}."
                            ),
                            block_pos={"x": pos_key[0], "y": pos_key[1], "z": pos_key[2]},
                            suggested_fix="Lower network rpm or redesign transmission to meet per-block limits.",
                        )
                    )

        if "su" in network:
            su = float(network["su"])
            for pos_key in member_keys:
                block = block_by_pos.get(pos_key)
                if not block:
                    continue
                su_rule = _matching_suffix_map(stress_limits_by_block, block["id"])
                if su_rule and abs(su) > su_rule[1]:
                    diagnostics.append(
                        MachineDiagnostic(
                            code="stress.exceeds_block_limit",
                            message=(
                                f"Network '{network['id']}' stress {su} exceeds max {su_rule[1]} "
                                f"for block '{block['id']}' at {pos_key}."
                            ),
                            block_pos={"x": pos_key[0], "y": pos_key[1], "z": pos_key[2]},
                            suggested_fix="Lower stress demand or increase capacity before this component.",
                        )
                    )

    for pattern in banned_patterns:
        if not isinstance(pattern, dict):
            continue
        banned_block_ids = pattern.get("block_ids", [])
        if not isinstance(banned_block_ids, list) or not banned_block_ids:
            continue
        machine_block_ids = {str(block["id"]) for block in blocks}
        if set(str(b) for b in banned_block_ids).issubset(machine_block_ids):
            diagnostics.append(
                MachineDiagnostic(
                    code=str(pattern.get("code", "banned.pattern")),
                    message=str(
                        pattern.get(
                            "description",
                            "Machine matches a banned pattern from the selected rule-pack.",
                        )
                    ),
                    block_pos=None,
                    suggested_fix="Adjust machine topology to avoid this banned pattern.",
                )
            )

    return [asdict(diagnostic) for diagnostic in diagnostics]


def validate_ir_or_raise(ir: dict[str, Any]) -> None:
    """Reject malformed AI output before compilation."""
    schema = _load_schema()

    validator = jsonschema.Draft202012Validator(schema)
    structural_errors = sorted(validator.iter_errors(ir), key=lambda e: list(e.path))
    if structural_errors:
        formatted = "\n".join(
            f"- {'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
            for err in structural_errors
        )
        raise IRValidationError(f"IR schema validation failed:\n{formatted}")

    semantic_errors = _check_semantics(ir)
    if semantic_errors:
        raise IRValidationError("IR semantic validation failed:\n" + "\n".join(f"- {e}" for e in semantic_errors))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/validate_create_ir.py path/to/ir.json", file=sys.stderr)
        return 2

    ir_path = Path(sys.argv[1])
    with ir_path.open("r", encoding="utf-8") as f:
        ir = json.load(f)

    try:
        validate_ir_or_raise(ir)
    except IRValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"IR valid: {ir_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
