# Create IR Schema + Validation Gate

This repository now includes a strict IR schema and a validation gate that should run before any compilation step.

## Files

- Schema: `schemas/create_ir.schema.json`
- Request schema: `schemas/generation_request.schema.json`
- Validator: `tools/validate_create_ir.py`

## IR shape

Top-level required keys:

- `blocks[]`
  - each block has `pos`, `id`, `properties`
- `networks[]`
  - kinetic connectivity groups
- `constraints[]`
  - user goals and limits:
    - `dimensions`
    - `su_target`
    - `rpm_range`
    - `allowed_blocks`
- `annotations`
  - intent metadata:
    - `generator_core`
    - `transmission_path`
    - `outputs`

## Validation strategy

1. Structural validation with JSON Schema draft 2020-12.
2. Semantic validation checks for compiler safety:
   - `rpm_range.min <= rpm_range.max`
   - no duplicate block coordinates
   - `annotations.outputs[].target_network_id` must reference an existing `networks[].id`
3. Create machine pass (`validate_create_machine`) emits structured diagnostics:
   - bounding box vs `dimensions` constraint
   - required orientation properties by block type
   - mechanical network membership + connectivity consistency
   - network stress/rpm checks against configured rule tables
   - unsupported block/entity combinations

Diagnostic shape:

```json
{
  "code": "rpm.exceeds_block_limit",
  "message": "Human-readable reason",
  "block_pos": { "x": 0, "y": 64, "z": 0 },
  "suggested_fix": "Actionable repair hint"
}
```

Malformed AI output must be rejected before compilation.

## Required generation request object

Before generation starts, the request context must include a non-ambiguous fingerprint and
all compatibility/performance fields:

- `fingerprint` (required, non-empty)
- `loader`
- `minecraft_version`
- `create_version`
- `installed_mods` (array of `{ id, version }`)
- `mechanic_policy` (`safe` | `quirks` | `exploits`)
- `performance_constraints`
  - `tps_safe`
  - `entity_caps.max_total`

`validate_generation_request_or_raise(...)` rejects generation when:

- `fingerprint` is missing or blank
- `installed_mods` contains duplicate IDs
- any mod version is ambiguous (`*`, `latest`, `any`, `unknown`)

## Usage

```bash
python tools/validate_create_ir.py path/to/ai-output.json
```

Important shell note:

- Use a real path and **do not** wrap it in angle brackets.
- ✅ `python tools/validate_create_ir.py ./tmp_ir.json`
- ❌ `python tools/validate_create_ir.py <temp_ir.json>`

In Bash/Git Bash, `<...>` is treated as input redirection syntax, not a placeholder argument.

- Exit code `0`: valid IR
- Exit code `1`: invalid IR (reject; do not compile)
- Exit code `2`: bad CLI usage
