"""Export the browser-safe ProUI runtime used by the static cockpit page.

The deployed 8876 cockpit is served as static files, so it cannot rely on the
FastAPI metadata endpoint. This module materializes the delivered page and
template metadata with their bound demo rows as ProUI ``mockData``. The browser
therefore renders standard ProUI cards without AP queries or prototype DOM.
"""
from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .data import NAMES
from .metadata import PAGE_IDS, ROOT, build_bundle

PAGE_NAMES = {
    "home": "首页",
    "overview": "全局经营看板",
    "operations": "运营 360 整体分析",
    "analysis": "穿透式问题分析",
}
PRO_COMPONENTS = {
    "bar": "ProBarChart",
    "bar-line": "ProDualAxisChart",
    "funnel": "ProFunnelChart",
    "horizontal-bar": "ProHorizontalBarChart",
    "kpiCard": "ProKpiCard",
    "mini-cpgraph": "ProMiniCpGraph",
    "progress": "ProProgressCard",
    "share-bar": "ProShareBar",
    "table": "ProDataTable",
    "title": "ProTitle",
}
CONTAINER_TYPES = {
    "group": "ProBiGroupContainer",
    "template": "ProBiTemplateContainer",
    "tab-container": "ProBiTabContainer",
    "segmented-strip": "ProBiSegmentedStrip",
    "split-container": "ProBiSplitContainer",
    "button-group": "ProButtonGroup",
}
RENDERABLE_TYPES = set(PRO_COMPONENTS) | set(CONTAINER_TYPES)
GAP_CODES = {
    "AP_BINDINGS_CONFLICT",
    "CHILD_DEFINITION_MISSING",
    "DATA_BINDING_MISSING",
    "MISSING_INTERACTIONS",
    "PRICE_TEMPLATE_MISSING",
}


def _bound_data(bundle: dict, component: dict):
    key = component.get("cockpitBindingKey")
    if not key:
        return None
    value = bundle["datasets"].get(key)
    if isinstance(value, dict) and value.get("error"):
        return None
    return deepcopy(value)


def _strip_unknown_children(components: list[dict], known_ids: set[str]) -> None:
    for component in components:
        if component.get("children"):
            component["children"] = [
                child for child in component["children"] if child in known_ids
            ]


def _materialize_template(bundle: dict, template_id: str) -> tuple[dict, list[dict]]:
    template = deepcopy(bundle["templates"][template_id])
    original = template["components"]
    components = []
    unrendered = []
    for component in original:
        component_type = component["type"]
        data = _bound_data(bundle, component)
        if component.get("cockpitBindingKey"):
            config = component.setdefault("dataConfig", {})
            config["sourceType"] = "mock"
            if component_type == "mini-cpgraph":
                graph_data = component.get("cockpitGraphData")
                config["mockData"] = deepcopy(graph_data) if graph_data else data
            else:
                config["mockData"] = data
        components.append(component)
    return (
        {
            "templateId": template_id,
            "meta": deepcopy(template.get("meta", {})),
            "components": components,
        },
        unrendered,
    )


def page_insights(slots: list[dict], template_id: str) -> list[dict]:
    """Keep slot declarations for one page; the host tab segment is dropped."""
    result = []
    for slot in slots:
        value = deepcopy(slot)
        segments = value.get("embedPath", {}).get("segments") or []
        if not segments or segments[0].get("templateId") != template_id:
            continue
        value["embedPath"]["segments"] = segments[1:]
        result.append(value)
    return result


def runtime_payload(bundle: dict | None = None) -> dict:
    bundle = bundle or build_bundle()
    templates = {}
    render_gaps = [gap for gap in bundle["gaps"] if gap["code"] in GAP_CODES]
    for template_id in bundle["templates"]:
        template, unrendered = _materialize_template(bundle, template_id)
        templates[template_id] = template
        render_gaps.extend(unrendered)
    pages = {}
    counts = {}
    for page, template_id in bundle["pages"].items():
        materialized = deepcopy(templates[template_id])
        components = materialized["components"]
        counts[page] = {
            "total": len(components),
            "types": dict(Counter(component["type"] for component in components)),
            "withData": sum(
                1 for component in components if component.get("cockpitBindingKey")
            ),
        }
        pages[page] = {
            "id": page,
            "title": PAGE_NAMES[page],
            "templateId": template_id,
            "name": materialized.get("meta", {}).get("name", PAGE_NAMES[page]),
            "components": components,
            "insights": page_insights(bundle["insights"], template_id),
        }

    source = json.loads((ROOT / "source.json").read_text())
    return {
        "source": {
            "branch": source["branch"],
            "commit": source["commit"],
            "fixture": bundle["source"],
        },
        "pages": pages,
        "roots": bundle["roots"],
        "templates": templates,
        "counts": counts,
        "gaps": render_gaps,
        "nodeStages": bundle["nodeStages"],
        "stageNames": NAMES,
        "renderer": "ProBiDashboard",
    }


def write_runtime(path: Path) -> dict:
    payload = runtime_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload
