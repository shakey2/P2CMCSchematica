#!/usr/bin/env python3
"""Rule-pack loading utilities keyed by (loader, minecraft_version, create_version)."""

from __future__ import annotations

import json
from difflib import get_close_matches
from pathlib import Path
from typing import Any

CAPABILITIES_ROOT = Path(__file__).resolve().parents[1] / "capabilities"
LEGACY_RULES_ROOT = Path(__file__).resolve().parents[1] / "rules"


class RulePackError(ValueError):
    """Raised when a rule-pack is missing or malformed."""


def rule_pack_path(loader: str, minecraft_version: str, create_version: str) -> Path:
    """Return canonical rule-pack path for a version tuple."""
    preferred_path = CAPABILITIES_ROOT / loader / minecraft_version / f"{create_version}.json"
    if preferred_path.exists():
        return preferred_path
    return LEGACY_RULES_ROOT / loader / minecraft_version / f"{create_version}.json"


def _require_dict(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RulePackError(f"Rule-pack field '{field_name}' must be an object.")
    return value


def validate_rule_pack_shape(rule_pack: dict[str, Any]) -> None:
    """Enforce minimal shape required by validators and generation plumbing."""
    supported_blocks = _require_dict(rule_pack.get("supported_blocks"), field_name="supported_blocks")
    kinetic_rules = _require_dict(rule_pack.get("kinetic_rules"), field_name="kinetic_rules")
    vanilla_mechanics = _require_dict(
        rule_pack.get("vanilla_mechanics"), field_name="vanilla_mechanics"
    )
    incompatibilities = _require_dict(
        rule_pack.get("incompatibilities"), field_name="incompatibilities"
    )

    for block_id, block_meta in supported_blocks.items():
        if not isinstance(block_id, str) or not block_id:
            raise RulePackError("supported_blocks keys must be non-empty block-id strings.")
        meta_dict = _require_dict(block_meta, field_name=f"supported_blocks.{block_id}")
        if "properties" in meta_dict and not isinstance(meta_dict["properties"], list):
            raise RulePackError(
                f"supported_blocks.{block_id}.properties must be an array when present."
            )

    for required_kinetic_field in (
        "mechanical_block_ids",
        "orientation_required_by_block",
        "rpm_limits_by_block",
        "stress_limits_by_block",
        "supported_entity_by_block",
        "connectivity",
    ):
        if required_kinetic_field not in kinetic_rules:
            raise RulePackError(
                f"kinetic_rules missing required field '{required_kinetic_field}'."
            )

    if "banned_patterns" not in incompatibilities:
        raise RulePackError("incompatibilities missing required field 'banned_patterns'.")

    if not isinstance(incompatibilities.get("banned_patterns"), list):
        raise RulePackError("incompatibilities.banned_patterns must be an array.")

    if "waterlogging" not in vanilla_mechanics or "observer_updates" not in vanilla_mechanics:
        raise RulePackError(
            "vanilla_mechanics must define 'waterlogging' and 'observer_updates' toggles."
        )


def load_rule_pack(loader: str, minecraft_version: str, create_version: str) -> dict[str, Any]:
    """Load and validate a rule-pack for the given environment tuple."""
    path = rule_pack_path(loader, minecraft_version, create_version)
    if not path.exists():
        raise RulePackError(
            "No rule-pack found for environment tuple "
            f"({loader}, {minecraft_version}, {create_version}) at {path}."
        )

    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise RulePackError("Rule-pack root must be a JSON object.")

    validate_rule_pack_shape(payload)
    return payload


def build_capability_index() -> dict[str, dict[str, list[str]]]:
    """Return available (loader -> minecraft_version -> [create_versions]) tuples."""
    index: dict[str, dict[str, list[str]]] = {}
    for root in (CAPABILITIES_ROOT, LEGACY_RULES_ROOT):
        if not root.exists():
            continue

        for loader_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            loader_key = loader_dir.name
            index.setdefault(loader_key, {})
            for mc_dir in sorted(p for p in loader_dir.iterdir() if p.is_dir()):
                existing = set(index[loader_key].get(mc_dir.name, []))
                discovered = {p.stem for p in mc_dir.glob("*.json") if p.is_file()}
                merged = sorted(existing | discovered)
                if merged:
                    index[loader_key][mc_dir.name] = merged

    return index


def nearest_create_version(
    loader: str, minecraft_version: str, requested_create_version: str
) -> str | None:
    """Pick the closest available Create version for a loader+minecraft tuple."""
    index = build_capability_index()
    create_versions = index.get(loader, {}).get(minecraft_version, [])
    if not create_versions:
        return None
    if requested_create_version in create_versions:
        return requested_create_version
    match = get_close_matches(requested_create_version, create_versions, n=1, cutoff=0.0)
    return match[0] if match else create_versions[-1]


def machine_rule_views(rule_pack: dict[str, Any]) -> dict[str, Any]:
    """Return normalized lookup tables for machine validation logic."""
    kinetic = rule_pack["kinetic_rules"]

    mechanical_ids = set(kinetic.get("mechanical_block_ids", []))
    orientation_required = {
        str(k): set(v) for k, v in kinetic.get("orientation_required_by_block", {}).items()
    }
    rpm_limits = {str(k): float(v) for k, v in kinetic.get("rpm_limits_by_block", {}).items()}
    su_limits = {str(k): float(v) for k, v in kinetic.get("stress_limits_by_block", {}).items()}
    supported_entity = {
        str(k): set(v) for k, v in kinetic.get("supported_entity_by_block", {}).items()
    }

    banned_patterns = rule_pack["incompatibilities"].get("banned_patterns", [])

    return {
        "mechanical_block_ids": mechanical_ids,
        "orientation_required_by_block": orientation_required,
        "rpm_limits_by_block": rpm_limits,
        "stress_limits_by_block": su_limits,
        "supported_entity_by_block": supported_entity,
        "connectivity_required": bool(kinetic.get("connectivity", {}).get("require_connected", True)),
        "banned_patterns": banned_patterns,
    }
