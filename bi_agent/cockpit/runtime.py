"""Materialize the delivered iba-demo dashboard for the isolated cockpit page.

The source of truth is the handed-off ``feature/demo_1021`` metadata.  The host
does not rewrite component positions, inject fixture datasets, or synthesise
missing cards.  Live reads use the delivered AP configuration; the retained
pdt-release snapshot is available only as explicit offline replay data.
"""
from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "web/static/cockpit/metadata"
METADATA = ROOT / "iba-demo-1021"
RELEASE = ROOT / "pdt-release-2109836674373566465"
SNAPSHOTS = RELEASE / "data-snapshots.json"
ACTIVATE_RULES = METADATA / "activate-rules.json"
PAGE_IDS = {
    "overview": "tab-bc6wp3k2",
    "operations": "tab-211tc4o0",
    "analysis": "tab-1suxx5hd",
}
PAGE_TEMPLATES = {
    "overview": "2112001069107167233",
    "operations": "2112434004503347202",
    "analysis": "2112061604959928321",
}
PAGE_LABELS = {
    "overview": "经营看板",
    "operations": "运营360整体分析",
    "analysis": "穿透式问题分析",
}
CONTAINERS = {
    "group", "template", "tab-container", "segmented-strip", "split-container",
    "button-group", "composite-filter", "title",
}
SUPPORTED_TYPES = CONTAINERS | {
    "bar", "bar-line", "funnel", "horizontal-bar", "kpiCard", "mini-cpgraph",
    "process-arc", "progress", "share-bar", "table",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _component_counts(components: list[dict]) -> dict:
    return {
        "total": len(components),
        "types": dict(Counter(component.get("type") for component in components)),
        "withData": sum(
            1
            for component in components
            if (component.get("dataConfig") or {}).get("sourceType") in {"ap", "request"}
        ),
    }


def _template_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "templateId" and isinstance(child, str):
                yield child
            elif key == "templateSwitchTargets" and isinstance(child, list):
                yield from (item for item in child if isinstance(item, str))
            else:
                yield from _template_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _template_refs(child)


def _component_ids(components: list[dict]) -> set[str]:
    return {component["id"] for component in components if component.get("id")}


def _target_components(slot: dict, root: list[dict], templates: dict[str, dict]) -> list[dict]:
    segments = (slot.get("embedPath") or {}).get("segments") or []
    template_id = segments[-1].get("templateId") if segments else None
    if template_id in templates:
        return templates[template_id].get("components", [])
    return root


def _collect_gaps(root: list[dict], templates: dict[str, dict]) -> list[dict]:
    gaps: list[dict] = []

    def inspect(component: dict, template_id: str | None = None) -> None:
        component_type = component.get("type")
        location = {"componentId": component.get("id")}
        if template_id:
            location["templateId"] = template_id
        if component_type not in SUPPORTED_TYPES:
            gaps.append({
                "code": "UNSUPPORTED_COMPONENT",
                "description": f"未找到类型 {component_type} 对应的 ProUI 组件",
                **location,
            })
        own_ids = _component_ids((templates.get(template_id) or {}).get("components", [])) if template_id else _component_ids(root)
        for child in component.get("children", []) or []:
            if child not in own_ids:
                gaps.append({
                    "code": "CHILD_DEFINITION_MISSING",
                    "description": f"父组件引用的子组件 {child} 未包含在同级配置中，原位置保留空位",
                    "missingChildId": child,
                    **location,
                })
        for nested in sorted(set(_template_refs(component))):
            if nested not in templates:
                gaps.append({
                    "code": "TEMPLATE_MISSING",
                    "description": f"组件引用的模板 {nested} 未包含在交付配置中",
                    "referencedTemplateId": nested,
                    **location,
                })

    for component in root:
        inspect(component)
    for template_id, template in templates.items():
        for component in template.get("components", []):
            inspect(component, template_id)

    for slot in _json(METADATA / "insights.json"):
        placement = slot.get("placement") or {}
        target_ids = _component_ids(_target_components(slot, root, templates))
        for key in ("anchorId", "afterId"):
            referenced = placement.get(key)
            if referenced and referenced not in target_ids:
                gaps.append({
                    "code": "INSIGHT_ANCHOR_MISSING",
                    "description": f"分析插槽 {slot['id']} 的落点组件 {referenced} 未包含在交付配置中",
                    "insightId": slot["id"],
                    "componentId": referenced,
                })

    return gaps


def release_payload() -> dict:
    source = _json(METADATA / "source.json")
    root = deepcopy(_json(METADATA / "components.json"))
    templates = deepcopy(_json(METADATA / "template-registry.json"))
    insights = _json(METADATA / "insights.json")
    activate_rules = _json(ACTIVATE_RULES)
    snapshot_source = _json(RELEASE / "source.json")
    snapshots = _json(SNAPSHOTS)

    pages = {}
    for page, tab_id in PAGE_IDS.items():
        template_id = PAGE_TEMPLATES[page]
        template = templates.get(template_id, {"components": [], "meta": {}})
        pages[page] = {
            "id": page,
            "tabId": tab_id,
            "templateId": template_id,
            "title": PAGE_LABELS[page],
            "components": deepcopy(template.get("components", [])),
            "insights": [
                deepcopy(slot)
                for slot in insights
                if ((slot.get("embedPath") or {}).get("segments") or [{}])[0].get("tabId") == tab_id
            ],
        }

    dashboard = {
        "id": "iba-demo-1021",
        "name": "储能经营风险驾驶舱",
        "description": "",
        "version": source["commit"][:7],
        "status": "active",
        "url": f"{source['repository']}/-/tree/{source['branch']}",
        "components": root,
        "gridCols": 120,
        "rowHeight": 10,
        "theme": "light",
        "headerLayout": {"componentIds": ["composite-filter-hzjk9t5q"]},
        "showHeaderTitle": True,
    }
    return {
        "source": {
            "kind": "iba-demo-metadata",
            "dashboardId": "iba-demo-1021",
            "name": "储能经营风险驾驶舱",
            "releaseUrl": dashboard["url"],
            "buildTime": source["importedAt"],
            "fetchedAt": source["importedAt"],
            "version": source["commit"][:7],
            "status": "active",
            "branch": source["branch"],
            "commit": source["commit"],
            "templateCount": len(templates),
            "totalComponents": len(root) + sum(
                len(template.get("components", [])) for template in templates.values()
            ),
            "insightComponents": source["insightComponents"],
            "activateRules": len(activate_rules),
            "dataMode": "ap-single-query",
            "credentialsStored": False,
            "snapshot": {
                "kind": snapshot_source["kind"],
                "dashboardId": snapshot_source["dashboardId"],
                "analysisRequests": len(snapshots.get("analysis", {})),
                "batchRequests": len(snapshots.get("batch", {})),
                "helmetRequests": len(snapshots.get("requests", {})),
                "credentialsStored": False,
            },
        },
        "dashboard": dashboard,
        "pages": pages,
        "templates": templates,
        "insights": insights,
        "activateRules": activate_rules,
        "counts": {
            "root": _component_counts(root),
            **{
                page: _component_counts(templates.get(PAGE_TEMPLATES[page], {}).get("components", []))
                for page in PAGE_IDS
            },
        },
        "gaps": _collect_gaps(root, templates),
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
