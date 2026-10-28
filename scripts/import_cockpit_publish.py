#!/usr/bin/env python3
"""Import a fetched PDT publish bundle into the cockpit metadata folder.

The dashboard is authored on ``pdt-dev`` and fetched as
``<dir>/dashboard.json`` plus ``<dir>/templates/<templateId>.json`` (see
``<dir>/fetch.json``).  This script converts that payload into the files the
cockpit runtime reads, without inventing, reordering or dropping components:

* ``components.json`` - root ``components`` array, byte-faithful values;
* ``template-registry.json`` - one entry per referenced template;
* ``source.json`` - provenance, hashes, counts, known gaps and host adaptations.

Only two host adaptations are performed, both documented in ``source.json``:

1. PDT publishes ``activateRules`` at dashboard level; ProUI reads them from a
   component's ``baseConfig.activateRules``, so they are restored on the tab
   container that owns the tabs (the shape the previous delivery used).
2. Rules that use the newer ``actions`` array are rewritten to ProUI's
   ``tab``/``helmet`` shape.  A rule whose action cannot be expressed in that
   shape, or whose surface ProUI does not support, is reported instead of being
   guessed.

Usage:
    python scripts/import_cockpit_publish.py <fetched-dir> [--target DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "bi_agent/web/static/cockpit/metadata/iba-demo-1021"
PROUI_SURFACES = {"button", "cardTitle", "headerAction", "insight", "progressFooter"}
ACTION_KEYS = {"switchTab": "tab", "selectHelmet": "helmet"}
SUPPORTED_TYPES = {
    "group", "template", "tab-container", "segmented-strip", "split-container",
    "button-group", "composite-filter", "title", "bar", "bar-line", "funnel",
    "horizontal-bar", "kpiCard", "mini-cpgraph", "process-arc", "progress",
    "share-bar", "table",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalise_rules(rules: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    """Return ProUI-shaped rules plus the rules and notes that cannot be carried."""
    shaped: list[dict] = []
    rejected: list[dict] = []
    notes: list[str] = []
    for rule in rules or []:
        source = rule.get("source") or {}
        surface = source.get("surface")
        if surface not in PROUI_SURFACES:
            rejected.append({
                "id": rule.get("id"),
                "surface": surface,
                "componentId": source.get("componentId"),
                "reason": "ProUI 只从组件 baseConfig.activateRules 注册 button/cardTitle/headerAction/insight/progressFooter",
            })
            continue
        if rule.get("tab") or rule.get("helmet"):
            shaped.append(rule)
            continue
        actions = rule.get("actions") or []
        target: dict = {}
        for action in actions:
            key = ACTION_KEYS.get(action.get("type"))
            if not key or key in target:
                rejected.append({
                    "id": rule.get("id"),
                    "surface": surface,
                    "componentId": source.get("componentId"),
                    "reason": f"无法在 ProUI 规则中表达的动作 {action.get('type')}",
                })
                target = {}
                break
            target[key] = {k: v for k, v in action.items() if k != "type"}
        if not target:
            continue
        merged = {k: v for k, v in rule.items() if k != "actions"}
        merged.update(target)
        shaped.append(merged)
        notes.append(f"{rule.get('id')}: actions→{'/'.join(sorted(target))}")
    return shaped, rejected, notes


def build(fetched: Path, target: Path) -> dict:
    dashboard = _load(fetched / "dashboard.json")
    if not dashboard.get("success"):
        raise SystemExit(f"根配置拉取失败：{dashboard.get('message')!r}")
    data = dashboard["data"]
    root = json.loads(data["configs"])
    components = root["components"]

    templates: dict[str, dict] = {}
    published: dict[str, dict] = {}
    for path in sorted((fetched / "templates").glob("*.json")):
        payload = _load(path)
        if not payload.get("success"):
            raise SystemExit(f"模板 {path.name} 拉取失败：{payload.get('message')!r}")
        item = payload["data"]
        config = json.loads(item["configs"])
        meta = {
            "name": item["name"],
            "lastUpdatedTime": item.get("lastUpdatedTime"),
            "version": item.get("version"),
        }
        if config.get("headerLayout") is not None:
            meta["headerLayout"] = config["headerLayout"]
        if config.get("showHeaderTitle") is not None:
            meta["showHeaderTitle"] = config["showHeaderTitle"]
        source = config.get("businessAttributeSource")
        if isinstance(source, dict):
            meta["businessAttributeSourceEnabled"] = bool(source.get("enabled"))
        templates[item["id"]] = {
            "templateId": item["id"],
            "meta": meta,
            "components": config.get("components", []),
            "gridCols": config.get("gridCols"),
            "rowHeight": config.get("rowHeight"),
            "theme": config.get("theme"),
        }
        published[item["id"]] = {
            "name": item["name"],
            "lastUpdatedTime": item.get("lastUpdatedTime"),
            "version": item.get("version"),
        }

    # ProUI registers activate rules from the owning component, never from the
    # dashboard root, so reattach the published rules to the tab container.
    tab_container = next(
        (c for c in components if c.get("type") == "tab-container"), None
    )
    if tab_container is None:
        raise SystemExit("根配置缺少 tab-container，无法挂载 activateRules")
    shaped, rejected, notes = _normalise_rules(root.get("activateRules") or [])
    tab_container.setdefault("baseConfig", {})["activateRules"] = shaped

    all_components = list(components) + [
        c for t in templates.values() for c in t["components"]
    ]
    types = {c.get("type") for c in all_components}
    if types - SUPPORTED_TYPES:
        raise SystemExit(f"出现未适配的组件类型：{sorted(types - SUPPORTED_TYPES)}")

    missing = []
    for scope, items in [("root", components)] + [
        (tid, t["components"]) for tid, t in templates.items()
    ]:
        ids = {c["id"] for c in items}
        for component in items:
            for child in component.get("children") or []:
                if child not in ids:
                    missing.append({
                        "templateId": scope if scope != "root" else None,
                        "componentId": component["id"],
                        "missingChildId": child,
                    })

    target.mkdir(parents=True, exist_ok=True)
    _dump(target / "components.json", components)
    _dump(target / "template-registry.json", templates)

    previous_path = target / "source.json"
    source = _load(previous_path) if previous_path.exists() else {}
    insights = _load(target / "insights.json") if (target / "insights.json").exists() else []
    source.update({
        "mode": "active-runtime-adapter",
        "notes": (
            "组件结构、指标编码与插槽位置按发布配置原样导入；运行时通过主服务实时取数，"
            "冻结快照仅用于显式回放模式。"
        ),
        "publishedAt": date.today().isoformat(),
        "published": {
            "platform": "pdt-dev.eimos.com",
            "dashboardId": data["id"],
            "name": data["name"],
            "url": data.get("url"),
            "version": data.get("version"),
            "lastUpdatedTime": data.get("lastUpdatedTime"),
            "templates": published,
        },
        "rootComponents": len(components),
        "templates": len(templates),
        "totalComponents": len(all_components),
        "componentTypes": dict(sorted(Counter(c.get("type") for c in all_components).items())),
        "dataSourceModes": dict(sorted(Counter(
            (c.get("dataConfig") or {}).get("sourceType") for c in all_components
        ).items())),
        "dashboard": {
            "gridCols": root.get("gridCols"),
            "rowHeight": root.get("rowHeight"),
            "theme": root.get("theme"),
            "headerLayout": root.get("headerLayout"),
            "showHeaderTitle": root.get("showHeaderTitle"),
        },
        "insights": len(insights),
        "insightComponents": len([
            path for path in (ROOT / "bi_agent/web/static/cockpit/insight-components").iterdir()
            if path.is_dir()
        ]),
        "adaptations": [
            "PDT 把 activateRules 发布在仪表盘根级；导入时回填到 tab-container.baseConfig.activateRules（ProUI 只从组件注册）。",
            *notes,
        ],
        "unsupportedRules": rejected,
        "knownIssues": missing,
    })
    for path in (target / "components.json", target / "template-registry.json"):
        source.setdefault("files", [])
        source["files"] = [f for f in source["files"] if f.get("file") != path.name]
        source["files"].append({"file": path.name, "sha256": _sha256(path)})
    source["files"] = sorted(source["files"], key=lambda item: item["file"])
    _dump(previous_path, source)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fetched", type=Path, help="directory holding dashboard.json and templates/")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    source = build(args.fetched, args.target)
    print(
        f"imported {source['published']['name']} ({source['published']['dashboardId']}) "
        f"updated {source['published']['lastUpdatedTime']}: "
        f"{source['rootComponents']} root + {source['templates']} templates = "
        f"{source['totalComponents']} components, {source['insights']} insights"
    )
    if source["unsupportedRules"]:
        print(f"unsupported activate rules: {len(source['unsupportedRules'])}")
    if source["knownIssues"]:
        print(f"known gaps: {source['knownIssues']}")


if __name__ == "__main__":
    main()
