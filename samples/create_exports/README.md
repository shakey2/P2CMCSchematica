# Create sample fixtures (text-encoded)

The repository stores Create sample schematic fixtures as `*.nbt.b64` to avoid raw
binary files in PR diffs.

Decode them into usable `.nbt` files with:

```bash
python tools/materialize_create_samples.py
```

By default this writes decoded files to `.tmp/create_exports/`.
