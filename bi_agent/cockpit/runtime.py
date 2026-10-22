"""Export the browser-safe ProUI runtime used by the static cockpit page.

The deployed 8876 cockpit is served as static files, so it cannot rely on the
FastAPI metadata endpoint. This module selects the components that have an
exact ProUI implementation and writes their delivered metadata and bound demo
data into one frozen runtime JSON document.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from .data import NAMES
from .metadata import OPS_NODES, PAGE_IDS, RISK_NODES, ROOT, build_bundle

PRO_COMPONENTS = {
    "bar": "ProBarChart",
    "bar-line": "ProDualAxisChart",
    "funnel": "ProFunnelChart",
    "horizontal-bar": "ProHorizontalBarChart",
    "mini-cpgraph": "ProMiniCpGraph",
    "share-bar": "ProShareBar",
}
OUTER_LEGEND_TYPES = {"bar", "bar-line", "funnel", "horizontal-bar"}
OPERATIONS_GRAPH = f"{PAGE_IDS['operations']}/mini-cpgraph-2dz7yyyf"
ANALYSIS_GRAPH = f"{PAGE_IDS['analysis']}/mini-cpgraph-93j6k86p"
ANNUAL_SALES = {
    "monthly": "2112009587516293121/bar-line-stx32yim",
    "products": "2112009587516293121/bar-tebs5kjx",
    "teams": "2112009587516293121/bar-line-swk58lta",
}
ANNUAL_VOLUME = {
    "monthly": "2112010750949113858/bar-nfodriiq",
    "teams": "2112010750949113858/bar-uvogx9g6",
}


def _component_index(bundle: dict) -> dict[tuple[str, str], dict]:
    return {
        (template_id, component["id"]): component
        for template_id, template in bundle["templates"].items()
        for component in template["components"]
    }


def _runtime_component(bundle: dict, index: dict, binding_key: str) -> dict:
    binding = bundle["bindings"].get(binding_key)
    if not binding:
        raise KeyError(f"missing cockpit binding: {binding_key}")
    component = deepcopy(index[(binding["templateId"], binding["componentId"])])
    component_type = component["type"]
    pro_component = PRO_COMPONENTS.get(component_type)
    if not pro_component:
        raise ValueError(f"no ProUI component for metadata type: {component_type}")
    component["showHeader"] = False
    if component_type in OUTER_LEGEND_TYPES:
        visualization = component.setdefault("visualization", {})
        visualization["legend"] = False
    return {
        "componentId": component["id"],
        "title": component.get("title", ""),
        "type": component_type,
        "proComponent": pro_component,
        "component": component,
        "data": deepcopy(bundle["datasets"][binding_key]),
    }


def runtime_payload(bundle: dict | None = None) -> dict:
    bundle = bundle or build_bundle()
    index = _component_index(bundle)
    selected = set(ANNUAL_SALES.values()) | set(ANNUAL_VOLUME.values())
    selected |= {OPERATIONS_GRAPH, ANALYSIS_GRAPH}
    components = {
        binding_key: _runtime_component(bundle, index, binding_key)
        for binding_key in sorted(selected)
    }
    mounts: dict[str, dict[str, dict]] = {}

    def mount(view: str, gap_id: str, binding_key: str, *, active_key: str | None = None) -> None:
        item = {"bindingKey": binding_key}
        if active_key:
            item["graphActiveKey"] = active_key
        mounts.setdefault(view, {})[gap_id] = item

    mount("overview-sales", "overview-sales:annual-chart:0", ANNUAL_SALES["monthly"])
    mount("overview-sales", "overview-sales:annual-chart:1", ANNUAL_SALES["products"])
    mount("overview-sales", "overview-sales:annual-chart:2", ANNUAL_SALES["teams"])
    mount("overview-volume", "overview-volume:annual-chart:0", ANNUAL_VOLUME["monthly"])
    mount("overview-volume", "overview-volume:annual-chart:1", ANNUAL_VOLUME["teams"])

    operations_views = {"operations": "opportunity"}
    operations_views.update({f"operations-{stage}": stage for stage in OPS_NODES})
    for view, stage in operations_views.items():
        mount(view, f"{view}:helmet:0", OPERATIONS_GRAPH, active_key=OPS_NODES[stage])

    for stage in RISK_NODES:
        view = f"analysis-{stage}"
        mount(view, f"{view}:helmet:0", ANALYSIS_GRAPH, active_key=RISK_NODES[stage])

    mount("operations-shipment", "operations-shipment:annual-chart:0", ANNUAL_VOLUME["teams"])
    mount("operations-shipment", "operations-shipment:annual-chart:1", ANNUAL_VOLUME["monthly"])

    source = json.loads((ROOT / "source.json").read_text())
    return {
        "source": {
            "branch": source["branch"],
            "commit": source["commit"],
            "fixture": bundle["source"],
        },
        "components": components,
        "mounts": mounts,
        "nodeStages": bundle["nodeStages"],
        "stageNames": NAMES,
    }


def write_runtime(path: Path) -> dict:
    payload = runtime_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload
