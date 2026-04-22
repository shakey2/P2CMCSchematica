# Create IR Schema + Validation Gate

This repository now includes a strict IR schema and a validation gate that should run before any compilation step.

## Files

- Schema: `schemas/create_ir.schema.json`
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

Malformed AI output must be rejected before compilation.

## Usage

```bash
python tools/validate_create_ir.py path/to/ai-output.json
```

- Exit code `0`: valid IR
- Exit code `1`: invalid IR (reject; do not compile)
- Exit code `2`: bad CLI usage
