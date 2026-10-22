#!/usr/bin/env python3
"""Regenerate the static ProUI runtime consumed by the cockpit browser page."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bi_agent.cockpit.runtime import write_runtime

OUTPUT = ROOT / "bi_agent/web/static/cockpit/metadata/runtime.json"


if __name__ == "__main__":
    payload = write_runtime(OUTPUT)
    counts = ", ".join(
        f"{page}={spec['total']}" for page, spec in payload["counts"].items()
    )
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: "
        f"{len(payload['templates'])} templates, {counts}"
    )
