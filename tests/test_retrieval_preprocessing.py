import importlib.util
from pathlib import Path


def _load_pipeline_module():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "schematic_pipeline.py"
    spec = importlib.util.spec_from_file_location("schematic_pipeline", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


pipeline = _load_pipeline_module()


def _example_ir(*, su: float, block_count: int, size: int, block_id: str = "create:cogwheel") -> dict:
    blocks = []
    for idx in range(block_count):
        blocks.append(
            {
                "pos": {"x": idx % size, "y": 0, "z": idx // max(1, size)},
                "id": block_id,
                "properties": {},
            }
        )

    return {
        "blocks": blocks,
        "networks": [{"id": "main", "members": [{"x": 0, "y": 0, "z": 0}], "su": su}],
        "constraints": [],
        "annotations": {"generator_core": [], "transmission_path": [{"x": 0, "y": 0, "z": 0}], "outputs": []},
    }


def test_summarize_ir_computes_expected_fields() -> None:
    ir = _example_ir(su=5000, block_count=8, size=3)

    summary = pipeline.summarize_ir(ir)

    assert summary["dimensions"] == {"x": 3, "y": 1, "z": 3}
    assert summary["component_counts"]["create:cogwheel"] == 8
    assert summary["network_topology"]["network_count"] == 1
    assert summary["stress"]["su_production"] == 5000
    assert "compact" in summary["tags"]
    assert "high-SU" in summary["tags"]
    assert "low-material" in summary["tags"]


def test_retrieval_first_context_prefers_summary_and_selective_full_ir() -> None:
    examples = [
        {"id": "compact_high", "ir": _example_ir(su=6000, block_count=16, size=4)},
        {"id": "large_low", "ir": _example_ir(su=512, block_count=256, size=16)},
    ]

    corpus = pipeline.build_retrieval_corpus(examples)
    context = pipeline.retrieval_first_prompt_context(
        {
            "required_tags": ["compact", "high-SU"],
            "target_su": 5000,
            "max_dimensions": {"x": 8, "y": 4, "z": 8},
        },
        corpus,
        top_k=2,
        include_full_ir=1,
    )

    assert [rec["id"] for rec in context["retrieved_summaries"]] == ["compact_high", "large_low"]
    assert [rec["id"] for rec in context["full_ir_examples"]] == ["compact_high"]
    assert "summary" in context["retrieved_summaries"][0]
    assert "retrieval_trace" in context["retrieved_summaries"][0]


def test_planner_pipeline_builds_debug_trace() -> None:
    examples = [
        {"id": "compact_high", "ir": _example_ir(su=6000, block_count=16, size=4)},
        {"id": "large_low", "ir": _example_ir(su=512, block_count=256, size=16)},
    ]

    planned = pipeline.build_planner_prompt_context(
        {
            "intent": {
                "size": {"x": 8, "y": 6, "z": 8},
                "su": 5000,
                "compactness": "compact",
                "exploit_tolerance": "safe",
            },
            "environment": {
                "loader": "forge",
                "minecraft_version": "1.20.1",
                "create_version": "0.5.1f",
            },
        },
        examples,
        top_k=2,
        include_full_ir=1,
    )

    assert planned["parsed_intent"]["required_tags"] == ["compact", "high-SU"]
    assert "vanilla_mechanics" in planned["selected_rules"]
    assert planned["planner_trace"]["why_this_rule"]
    assert planned["planner_trace"]["why_this_example"]
    assert planned["planner_trace"]["why_this_example"][0]["id"] == "compact_high"
