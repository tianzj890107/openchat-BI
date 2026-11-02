"""Delivered metadata, native ProUI runtime, and cockpit routes must agree."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bi_agent.cockpit.metadata import PAGE_IDS, ROOT, build_bundle
from bi_agent.cockpit.prototype import PrototypeSource
from bi_agent.cockpit.router import build_cockpit_router
from bi_agent.cockpit.runtime import (
    HELMET_VIEW_PATH, METADATA, PAGE_TEMPLATES, release_payload, runtime_payload,
)


def _target_ids(slot, roots, templates):
    segments = (slot.get("embedPath") or {}).get("segments") or []
    template_id = segments[-1].get("templateId") if segments else ""
    components = templates.get(template_id, {}).get("components", []) if template_id else roots
    return {component["id"] for component in components if component.get("id")}


def _host_template_registry():
    registry = json.loads((ROOT / "template-registry.json").read_text())
    for template in registry.values():
        for component in template.get("components", []):
            graph_config = component.get("graphConfig")
            if isinstance(graph_config, dict) and "helmetViewUrl" in graph_config:
                graph_config["helmetViewUrl"] = HELMET_VIEW_PATH
    return registry


def test_build_bundle_preserves_delivered_data_without_fixture_substitution():
    original = (ROOT / "template-registry.json").read_bytes()
    bundle = build_bundle()

    assert (ROOT / "template-registry.json").read_bytes() == original
    assert set(bundle["pages"]) == {"overview", "operations", "analysis"}
    assert bundle["sourceMode"] == "upstream-ap"
    assert bundle["datasets"] == {} and bundle["bindings"] == {} and bundle["overrides"] == []
    assert bundle["roots"] == runtime_payload()["dashboard"]["components"]
    assert bundle["templates"] == _host_template_registry()
    assert len(bundle["insights"]) == 15
    assert len(bundle["activateRules"]) == 6

    all_components = bundle["roots"] + [
        component
        for template in bundle["templates"].values()
        for component in template.get("components", [])
    ]
    assert len(all_components) == 142
    assert {(component.get("dataConfig") or {}).get("sourceType") for component in all_components} <= {"ap", "mock"}
    assert all("cockpitBindingKey" not in component for component in all_components)

    missing = [gap for gap in bundle["gaps"] if gap["code"] == "CHILD_DEFINITION_MISSING"]
    assert [(gap["templateId"], gap["componentId"], gap["missingChildId"]) for gap in missing] == [
        ("2112062888320483329", "group-9ypz7vwt", "share-bar-79fsomq9")
    ]
    assert "AP_SNAPSHOT_BASIS" not in {gap["code"] for gap in bundle["gaps"]}


def test_activate_rules_cover_sales_risk_and_every_insight_anchor_is_delivered():
    bundle = build_bundle()
    rules = bundle["activateRules"]
    sales = next(rule for rule in rules if rule["source"]["actionKey"] == "1793158849339")
    assert sales["source"]["componentId"] == "progress-y5dumxio"
    assert sales["actions"] == [
        {
            "type": "switchTab",
            "containerId": "tab-container-zm9eyxne",
            "embedPath": [],
            "tabId": "tab-1suxx5hd",
        },
        {
            "type": "selectHelmet",
            "componentId": "mini-cpgraph-93j6k86p",
            "embedPath": [{
                "containerId": "tab-container-zm9eyxne",
                "kind": "tab",
                "tabId": "tab-1suxx5hd",
                "templateId": "2112061604959928321",
            }],
            "nodeId": "2109840325158682625",
            "nodeName": "商机获取",
        },
    ]

    for slot in bundle["insights"]:
        assert slot["embedPath"]["segments"]
        target_ids = _target_ids(slot, bundle["roots"], bundle["templates"])
        for key in ("anchorId", "afterId"):
            referenced = (slot.get("placement") or {}).get(key)
            assert not referenced or referenced in target_ids, (slot["id"], key, referenced)
    assert {slot["id"] for slot in bundle["insights"]} >= {
        "bid-status-note", "quote-summary", "bid-summary", "order-sign-summary",
        "sales-shipment-issues", "opportunity-risk", "opportunity-coverage-note",
        "order-risk-summary", "shipment-risk-summary", "shipment-overdue-note",
        "shipment-cause-breakdown", "shipment-task-order", "star-product-order-list",
        "affected-order-list", "overdue-order-list",
    }


def test_runtime_is_reproducible_and_preserves_upstream_components():
    stored = json.loads((METADATA.parent / "runtime.json").read_text())
    assert stored == runtime_payload() == release_payload()
    assert stored["renderer"] == "ProBiDashboard"
    assert stored["mode"] == "release"
    assert stored["source"]["dashboardId"] == "iba-demo-1021"
    assert stored["source"]["version"] == "be99db5"
    assert stored["source"]["commit"] == "be99db5cbbda4496b62d6c14e7f4c5e793a77476"
    assert stored["source"]["templateCount"] == 13
    assert stored["source"]["totalComponents"] == 142
    assert stored["source"]["activateRules"] == 6
    assert stored["source"]["dataMode"] == "ap-single-query"
    assert len(stored["templates"]) == 13
    serialized = json.dumps(stored, ensure_ascii=False)
    assert "3项风险" not in serialized
    assert serialized.count('"label": "查看风险"') == 8
    assert len(stored["activateRules"]) == 6
    assert {page: len(page_spec["insights"]) for page, page_spec in stored["pages"].items()} == {
        "overview": 0, "operations": 5, "analysis": 10,
    }
    assert set(stored["pages"]["analysis"]["insights"][0]) >= {"id", "embedPath", "placement"}
    assert set(stored["pages"]) == {"overview", "operations", "analysis"}
    assert stored["counts"]["operations"] == {
        "total": 46,
        "types": {
            "title": 4, "button-group": 1, "progress": 10, "mini-cpgraph": 1,
            "template": 1, "funnel": 1, "kpiCard": 16, "share-bar": 4,
            "group": 4, "horizontal-bar": 2, "segmented-strip": 2,
        },
        "withData": 33,
    }
    assert stored["counts"]["analysis"] == {
        "total": 10,
        "types": {"progress": 5, "mini-cpgraph": 1, "template": 1, "title": 2, "button-group": 1},
        "withData": 5,
    }

    source_registry = _host_template_registry()
    for page, template_id in PAGE_TEMPLATES.items():
        assert stored["templates"][template_id] == source_registry[template_id]
        assert stored["pages"][page]["components"] == source_registry[template_id]["components"]
    delivered_root = json.loads((METADATA / "components.json").read_text())
    assert stored["dashboard"]["components"] == delivered_root
    assert [component["id"] for component in stored["dashboard"]["components"]] == [
        component["id"] for component in delivered_root
    ]


def test_delivered_month_default_period_is_preserved():
    payload = runtime_payload()
    filter_component = next(
        component for component in payload["dashboard"]["components"]
        if component.get("type") == "composite-filter"
    )
    assert filter_component["baseConfig"]["defaultValue"]["values"]["YWLN_D044"] == "2025-10"
    operations = next(
        component for component in payload["pages"]["operations"]["components"]
        if component.get("type") == "button-group"
    )
    assert next(item for item in operations["buttonGroupConfig"]["items"] if item.get("default"))["grain"] == "year"


def test_metadata_api_exposes_delivered_rules_and_keeps_legacy_analysis_endpoints(tmp_path):
    app = FastAPI()
    app.include_router(build_cockpit_router(lambda: tmp_path))
    client = TestClient(app)
    metadata = client.get("/api/cockpit/metadata").json()
    assert metadata["sourceMode"] == "upstream-ap"
    assert len(metadata["activateRules"]) == 6
    assert metadata["datasets"] == {} and metadata["bindings"] == {}

    original = client.get("/api/cockpit/snapshot").json()
    exact = client.get("/api/cockpit/snapshot?source=prototype").json()
    assert original["snapshotId"] != exact["snapshotId"]
    assert client.get("/api/cockpit/snapshot?source=prototype&period=2025-09").status_code == 422
    evidence = client.get("/api/cockpit/evidence?source=prototype&stage=shipment").json()
    assert evidence["snapshotId"] == exact["snapshotId"]
    assert evidence["records"][0]["id"] == "SO-2026-0318"


def test_prototype_source_remains_available_only_for_explicit_standalone_analysis():
    source = PrototypeSource()
    snapshot = source.snapshot()
    evidence = source.evidence(snapshot, "shipment")
    assert evidence["sourceMode"] == "prototype"
    assert evidence["records"][0]["id"] == "SO-2026-0318"
    assert len(source.evidence(snapshot, "opportunity")["records"]) == 10


def test_runtime_reports_live_ap_single_query_mode_and_only_real_gaps():
    payload = release_payload()
    assert payload["source"]["commit"] == "be99db5cbbda4496b62d6c14e7f4c5e793a77476"
    assert payload["source"]["dataMode"] == "ap-single-query"
    assert {gap["code"] for gap in payload["gaps"]} == {"CHILD_DEFINITION_MISSING"}
    overview = payload["pages"]["overview"]["components"]
    progress = {component["id"]: component for component in overview if component.get("type") == "progress"}
    assert [item["identifierCode"] for item in progress["progress-y5dumxio"]["dataConfig"]["measure"]] == ["YWLN_M0001"]
    assert [item["identifierCode"] for item in progress["progress-djttwi50"]["dataConfig"]["measure"]] == ["M0013"]
    assert [item["identifierCode"] for item in progress["progress-rna6k8bw"]["dataConfig"]["measure"]] == ["M0019"]
