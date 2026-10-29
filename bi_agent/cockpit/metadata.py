"""Expose delivered iba-demo metadata without prototype or fixture substitution.

The upstream JSON is immutable. Missing children and unresolved insight anchors
are reported in ``gaps``; no dataset is bound to a component that did not
deliver one. Live AP failures remain visible at the original card position.
"""
from __future__ import annotations

from pathlib import Path

from .runtime import PAGE_TEMPLATES, release_payload


ROOT = Path(__file__).resolve().parents[1] / "web/static/cockpit/metadata/iba-demo-1021"
PAGE_IDS = dict(PAGE_TEMPLATES)
OPS_NODES = {
    "opportunity": "2109848488855519233",
    "quotation": "2112022555167604737",
    "bid": "2109848488918433794",
    "order": "2109848488926822401",
    "shipment": "2109848488926822402",
}
RISK_NODES = {
    "opportunity": "2109840325158682625",
    "order": "2109840573998350338",
    "shipment": "2109840696539136002",
}


def build_bundle() -> dict:
    payload = release_payload()
    return {
        "pages": PAGE_IDS,
        "roots": payload["dashboard"]["components"],
        "templates": payload["templates"],
        "datasets": {},
        "bindings": {},
        "insights": payload["insights"],
        "activateRules": payload["activateRules"],
        "nodeStages": {value: key for key, value in OPS_NODES.items()}
        | {value: key for key, value in RISK_NODES.items()},
        "gaps": payload["gaps"],
        "overrides": [],
        "sourceMode": "upstream-ap",
        "source": payload["source"],
    }
