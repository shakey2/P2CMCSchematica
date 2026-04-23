import importlib.util
import sys
import types
from pathlib import Path


def _load_module(name: str, rel_path: str):
    module_path = Path(__file__).resolve().parents[1] / rel_path
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rule_pack = _load_module("rule_pack", "tools/rule_pack.py")

jsonschema_stub = types.SimpleNamespace(
    Draft202012Validator=lambda schema: types.SimpleNamespace(iter_errors=lambda _: [])
)
sys.modules.setdefault("jsonschema", jsonschema_stub)
validator = _load_module("validate_create_ir", "tools/validate_create_ir.py")


def test_rule_pack_loads_for_environment_tuple() -> None:
    pack = rule_pack.load_rule_pack("forge", "1.20.1", "0.5.1f")

    assert "supported_blocks" in pack
    assert "kinetic_rules" in pack
    assert "vanilla_mechanics" in pack
    assert "incompatibilities" in pack


def test_generation_request_requires_matching_rule_pack() -> None:
    request = {
        "fingerprint": "abc123",
        "loader": "forge",
        "minecraft_version": "1.20.1",
        "create_version": "0.5.1f",
        "installed_mods": [{"id": "create", "version": "0.5.1f"}],
        "mechanic_policy": "safe",
        "performance_constraints": {"tps_safe": True, "entity_caps": {"max_total": 64}},
    }

    validator.validate_generation_request_or_raise(request)


def test_banned_pattern_diagnostic_comes_from_rule_pack() -> None:
    ir = {
        "blocks": [
            {"id": "create:gearbox", "pos": {"x": 0, "y": 0, "z": 0}, "properties": {"axis": "x"}},
            {
                "id": "create:large_cogwheel",
                "pos": {"x": 1, "y": 0, "z": 0},
                "properties": {"axis": "x"},
            },
        ],
        "networks": [
            {
                "id": "n1",
                "members": [{"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0}],
                "rpm": 16,
                "su": 256,
            }
        ],
        "constraints": [],
    }

    pack = rule_pack.load_rule_pack("forge", "1.20.1", "0.5.1f")
    diagnostics = validator.validate_create_machine(ir, pack)

    assert any(d["code"] == "banned.mixed_axis_gearbox_ladder" for d in diagnostics)


def test_generation_request_returns_machine_readable_fallback_suggestions() -> None:
    request = {
        "fingerprint": "abc123",
        "loader": "forge",
        "minecraft_version": "1.20.1",
        "create_version": "0.5.1f",
        "installed_mods": [{"id": "create", "version": "0.5.1f"}],
        "mechanic_policy": "safe",
        "performance_constraints": {"tps_safe": True, "entity_caps": {"max_total": 64}},
        "requested_features": {
            "block_chain": ["create:shaft", "create:nonexistent_block"],
            "target_su": 20000,
        },
    }

    try:
        validator.validate_generation_request_or_raise(request)
        raise AssertionError("Expected unsupported requested_features to fail validation.")
    except validator.IRValidationError as exc:
        text = str(exc)
        assert "fallback_suggestions" in text
        assert "alternative_block_chain" in text
        assert "reduced_target_su" in text


def test_generation_request_rejects_non_vanilla_non_create_namespaces() -> None:
    request = {
        "fingerprint": "abc123",
        "loader": "forge",
        "minecraft_version": "1.20.1",
        "create_version": "0.5.1f",
        "installed_mods": [{"id": "create", "version": "0.5.1f"}],
        "mechanic_policy": "safe",
        "performance_constraints": {"tps_safe": True, "entity_caps": {"max_total": 64}},
        "requested_features": {
            "block_chain": ["thermal:machine_frame"],
        },
    }

    try:
        validator.validate_generation_request_or_raise(request)
        raise AssertionError("Expected unsupported namespace to fail validation.")
    except validator.IRValidationError as exc:
        assert "UNSUPPORTED_MOD_NAMESPACE" in str(exc)
