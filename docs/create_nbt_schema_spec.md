# Create `.nbt` Schematic Schema (Observed Samples)

This document captures the observed root layout and nesting from the sample files in `samples/create_exports/`.
Use `tools/probe_nbt_schema.py` to re-verify against new files.

## Sample set

- `samples/create_exports/create_sample_01.nbt.b64 (decode to .nbt)`
- `samples/create_exports/create_sample_02.nbt.b64 (decode to .nbt)`
- `samples/create_exports/create_sample_03.nbt.b64 (decode to .nbt)`

All three are gzip-compressed NBT compound roots with an empty root name (`""`).

## Required keys

Observed in every sample:

- `size: int[3]`
  - Axis order is `[x, y, z]`.
- `palette: list<compound>`
  - Each entry has:
    - `Name: string` (block id, e.g. `minecraft:stone`)
    - Optional `Properties: compound<string,string>`
- `blocks: list<compound>`
  - Each entry has:
    - `pos: int[3]` local block coordinate
    - `state: int` palette index into `palette`
    - Optional `nbt: compound` for block-entity payload
- `entities: list<compound>`
  - Empty list is valid.

## Optional keys

Observed in one or more samples only:

- `DataVersion: int`
- `author: string`
- `DeployedBy: string`
- `Version: int`
- `MinecraftDataVersion: int`

## Coordinate conventions

- `size` defines the schematic bounds as integer extents `[x, y, z]`.
- `blocks[*].pos` uses integer local coordinates relative to the schematic origin.
- `entities[*].blockPos` (when present) uses integer local block coordinates.
- `entities[*].pos` (when present) uses floating-point world-local coordinates (`double[3]`).

## Compression expectations

- Sample files are gzip-compressed (`0x1f8b` header).
- The probe script supports both gzip-compressed and raw (uncompressed) NBT payloads.

## Version tags

Version-like fields seen across samples:

- `DataVersion` (Mojang data version id)
- `Version` (schema/version marker)
- `MinecraftDataVersion` (explicit MC data version marker)

Because multiple conventions appear, consumers should:

1. Prefer `DataVersion` if present.
2. Fall back to `MinecraftDataVersion` / `Version` when needed.
3. Treat missing version fields as unknown and handle defensively.

## Fast verification

```bash
python tools/materialize_create_samples.py && python tools/probe_nbt_schema.py .tmp/create_exports
```

This prints key paths and inferred types for each `.nbt` file.
