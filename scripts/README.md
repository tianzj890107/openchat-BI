# Project scripts

Standalone maintenance and development scripts are grouped by responsibility:

- `run.py`: convenience launcher for the Open Claude CLI
- `data/`: database builds, seed data, schema updates, and one-off backfills
- `ontology/`: ontology workbook registration and maintenance
- `build_hyperfusion_metadata.mjs`: HyperFusion metadata workbook generator
- `test_extract_section.js`: frontend extraction experiment/test script

Run Python scripts from the repository root, for example:

```bash
python scripts/run.py
python scripts/data/build_hyperfusion_db.py
python scripts/ontology/register_cfo_ontology.py
```

The HyperFusion database builder additionally requires the data dependency:

```bash
pip install -e '.[data]'
```

The Python maintenance scripts resolve `dataset/` from their own location, so
their data targets do not depend on the shell's current working directory.
