import json
from pathlib import Path


def _load_schema() -> dict:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "generation_request.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_generation_request_schema_requires_fingerprint_and_context_fields() -> None:
    schema = _load_schema()

    required = set(schema["required"])
    assert {
        "fingerprint",
        "loader",
        "minecraft_version",
        "create_version",
        "installed_mods",
        "mechanic_policy",
        "performance_constraints",
    }.issubset(required)


def test_generation_request_schema_defines_policy_and_performance_shape() -> None:
    schema = _load_schema()
    props = schema["properties"]

    assert props["mechanic_policy"]["enum"] == ["safe", "quirks", "exploits"]

    perf = props["performance_constraints"]
    assert set(perf["required"]) == {"tps_safe", "entity_caps"}
    assert perf["properties"]["entity_caps"]["required"] == ["max_total"]

    requested_features = props["requested_features"]
    assert set(requested_features["properties"]) == {"block_chain", "target_su"}
