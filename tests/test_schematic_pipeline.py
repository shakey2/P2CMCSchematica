import importlib.util
import json
from pathlib import Path


def _load_pipeline_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "schematic_pipeline.py"
    spec = importlib.util.spec_from_file_location("schematic_pipeline", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


pipeline = _load_pipeline_module()


def _load_fixture(name: str) -> dict:
    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_decompile_extracts_block_entities_by_position_and_whitelists_payload() -> None:
    schematic = _load_fixture("create_block_entity_heavy_schematic.json")

    ir = pipeline.decompile_schematic(schematic)

    assert set(ir["block_entities"]) == {"0,0,0", "1,0,0", "2,0,0", "4,1,1"}

    kinetic_payload = ir["block_entities"]["0,0,0"]
    assert kinetic_payload["id"] == "create:kinetic_block_entity"
    assert "Speed" in kinetic_payload
    assert "DestroyMe" not in kinetic_payload

    belt_payload = ir["block_entities"]["1,0,0"]
    assert belt_payload["id"] == "create:belt_block_entity"
    assert "Length" in belt_payload
    assert "Transient" not in belt_payload

    # Non-Create entities are preserved as-is.
    barrel_payload = ir["block_entities"]["4,1,1"]
    assert barrel_payload["id"] == "minecraft:barrel"
    assert "LootTable" in barrel_payload


def test_roundtrip_is_stable_and_equivalent() -> None:
    schematic = _load_fixture("create_block_entity_heavy_schematic.json")

    first_ir = pipeline.decompile_schematic(schematic)
    recompiled = pipeline.compile_schematic(first_ir)
    second_ir = pipeline.decompile_schematic(recompiled)

    assert first_ir == second_ir
    assert pipeline.normalize_roundtrip(first_ir) == first_ir

    # Ensure compile output keeps sanitized block-entity payloads.
    be_payload = next(b["nbt"] for b in recompiled["blocks"] if b["pos"] == [0, 0, 0])
    assert "DestroyMe" not in be_payload
    assert be_payload["Speed"] == 32.0
