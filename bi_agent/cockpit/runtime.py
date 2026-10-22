"""Materialize the published pdt dashboard for the isolated cockpit page.

The release page at ``/dashboard/release/2109836674373566465`` is itself one
ProUI ``ProBiDashboard``: a header composite filter plus a tab container whose
four tabs resolve to frozen template configs.  The page keeps the original
dashboard/template responses on disk and replays the captured AP read responses
from ``data-snapshots.json``.  No SSO cookie or user token is stored here.
"""
from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "web/static/cockpit/metadata"
RELEASE = ROOT / "pdt-release-2109836674373566465"
INSIGHTS = ROOT / "iba-demo-1021/insights.json"
RELEASE_ID = "2109836674373566465"
PAGE_IDS = {
    "home": "tab-qqzt1nj6",
    "overview": "tab-bc6wp3k2",
    "operations": "tab-211tc4o0",
    "analysis": "tab-1suxx5hd",
}
PAGE_TEMPLATES = {
    "home": "2113106174095179778",
    "overview": "2112001069107167233",
    "operations": "2112434004503347202",
    "analysis": "2112061604959928321",
}
CONTAINERS = {
    "group", "template", "tab-container", "segmented-strip", "split-container",
    "button-group", "composite-filter", "title",
}
SUPPORTED_TYPES = CONTAINERS | {
    "bar", "bar-line", "funnel", "horizontal-bar", "kpiCard", "mini-cpgraph",
    "progress", "share-bar", "table",
}


def _record(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("data")
    if not isinstance(value, dict) or not isinstance(value.get("configs"), str):
        raise ValueError(f"invalid dashboard record: {path}")
    return deepcopy(value)


def _config(record: dict) -> dict:
    return json.loads(record["configs"])


def _component_counts(components: list[dict]) -> dict:
    return {
        "total": len(components),
        "types": dict(Counter(component.get("type") for component in components)),
        "withData": sum(
            1
            for component in components
            if (component.get("dataConfig") or {}).get("mockData") is not None
            or (component.get("dataConfig") or {}).get("sourceType") in {"ap", "request"}
        ),
    }


def _template_record(record: dict) -> dict:
    return {
        "templateId": record["id"],
        "meta": {
            "name": record.get("name", ""),
            "description": record.get("description", ""),
            "version": record.get("version", ""),
            "status": record.get("status", ""),
            "url": record.get("url", ""),
        },
        "components": _config(record).get("components", []),
    }


def _page_insights(template_id: str) -> list[dict]:
    """Return delivery slots owned by one page for the whole-dashboard renderer."""
    result = []
    for slot in json.loads(INSIGHTS.read_text(encoding="utf-8")):
        value = deepcopy(slot)
        segments = value.get("embedPath", {}).get("segments") or []
        if not segments or segments[0].get("templateId") != template_id:
            continue
        result.append(value)
    return result


def _collect_gaps(root: dict, templates: dict[str, dict]) -> list[dict]:
    gaps: list[dict] = []

    def template_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "templateId" and isinstance(child, str):
                    yield child
                elif key == "templateSwitchTargets" and isinstance(child, list):
                    yield from (item for item in child if isinstance(item, str))
                else:
                    yield from template_refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from template_refs(child)

    for component in root.get("components", []):
        component_type = component.get("type")
        if component_type not in SUPPORTED_TYPES:
            gaps.append({
                "code": "UNSUPPORTED_COMPONENT",
                "componentId": component.get("id"),
                "description": f"未找到类型 {component_type} 对应的 ProUI 组件",
            })
        for template_id in sorted(set(template_refs(component))):
            if template_id not in templates:
                gaps.append({
                    "code": "TEMPLATE_MISSING",
                    "componentId": component.get("id"),
                    "templateId": template_id,
                    "description": f"组件引用的模板 {template_id} 未包含在发布配置中",
                })

    for template_id, template in templates.items():
        for component in template.get("components", []):
            component_type = component.get("type")
            if component_type not in SUPPORTED_TYPES:
                gaps.append({
                    "code": "UNSUPPORTED_COMPONENT",
                    "componentId": component.get("id"),
                    "templateId": template_id,
                    "description": f"未找到类型 {component_type} 对应的 ProUI 组件",
                })
            for nested in sorted(set(template_refs(component))):
                if nested not in templates:
                    gaps.append({
                        "code": "TEMPLATE_MISSING",
                        "componentId": component.get("id"),
                        "templateId": template_id,
                        "description": f"组件引用的模板 {nested} 未包含在发布配置中",
                    })
    return gaps


def release_payload() -> dict:
    source = json.loads((RELEASE / "source.json").read_text(encoding="utf-8"))
    root = _record(RELEASE / "dashboard.json")
    root_config = _config(root)
    templates = {}
    for path in sorted((RELEASE / "templates").glob("*.json"), key=lambda value: value.stem):
        record = _record(path)
        templates[record["id"]] = _template_record(record)

    pages = {}
    for page, tab_id in PAGE_IDS.items():
        template_id = PAGE_TEMPLATES[page]
        template = templates.get(template_id, {"components": [], "meta": {}})
        pages[page] = {
            "id": page,
            "tabId": tab_id,
            "templateId": template_id,
            "title": template.get("meta", {}).get("name", page),
            "components": template.get("components", []),
            "insights": _page_insights(template_id),
        }

    components = root_config.get("components", [])
    dashboard = {
        "id": root["id"],
        "name": root.get("name", ""),
        "description": root.get("description", ""),
        "version": root.get("version", ""),
        "status": root.get("status", ""),
        "url": root.get("url", ""),
        "components": components,
        "gridCols": root_config.get("gridCols", 120),
        "rowHeight": root_config.get("rowHeight", 10),
        "theme": root_config.get("theme", "light"),
        "headerLayout": root_config.get("headerLayout") or {},
        "showHeaderTitle": bool(root_config.get("showHeaderTitle")),
    }
    return {
        "source": {
            "kind": source["kind"],
            "dashboardId": source["dashboardId"],
            "name": source["name"],
            "releaseUrl": source["releaseUrl"],
            "buildTime": source["buildTime"],
            "fetchedAt": source["fetchedAt"],
            "version": source["dashboardVersion"],
            "status": source["dashboardStatus"],
            "templateCount": source["templates"],
            "totalComponents": len(components) + sum(
                len(template.get("components", [])) for template in templates.values()
            ),
            "credentialsStored": False,
        },
        "dashboard": dashboard,
        "pages": pages,
        "templates": templates,
        "counts": {
            "root": _component_counts(components),
            **{
                page: _component_counts(template.get("components", []))
                for page, template in ((page, templates[PAGE_TEMPLATES[page]]) for page in PAGE_IDS)
            },
        },
        "gaps": _collect_gaps(root_config, templates),
        "renderer": "ProBiDashboard",
        "mode": "release",
    }


def runtime_payload() -> dict:
    return release_payload()


def write_runtime(path: Path) -> dict:
    payload = release_payload()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
