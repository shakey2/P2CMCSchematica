#!/usr/bin/env python3
"""Validate Create IR JSON before compilation.

Usage:
  python tools/validate_create_ir.py path/to/ir.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install with `pip install jsonschema`."
    ) from exc


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "create_ir.schema.json"


class IRValidationError(ValueError):
    """Raised when AI output is malformed and must be rejected."""


def _load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


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
