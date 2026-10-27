from __future__ import annotations

import json
from pathlib import Path

from bi_agent.process360.catalog import Process360Catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "dataset" / "process360" / "ywln-v3.1" / "catalog.json"


def _catalog() -> Process360Catalog:
    return Process360Catalog.from_file(CATALOG)


def test_catalog_header_and_counts() -> None:
    catalog = _catalog()
    assert catalog.catalog_id == "ywln-process360-v3.1"
    assert catalog.version == "V3.1"
    summary = catalog.summary()
    assert summary["metrics"] == 206
    assert summary["business_rules"] == 84
    assert summary["scenarios"] == 5
    assert summary["processes"] == 7
    assert summary["activities"] == 26
    assert summary["actions"] == 16
    assert summary["sops"] == 18


def test_all_sops_parse_with_skills() -> None:
    catalog = _catalog()
    assert [sop["id"] for sop in catalog.sops] == [f"P{i:02d}" for i in range(1, 19)]
    for sop in catalog.sops:
        assert sop.get("title")
        assert sop.get("applicableQuestion")
        assert sop.get("skills")
        assert all(skill.startswith("S0") for skill in sop["skills"])


def test_five_scenarios_have_complete_bundles() -> None:
    catalog = _catalog()
    expected_tasks = {"SC01": 4, "SC02": 1, "SC03": 1, "SC04": 1, "SC05": 1}
    for scenario in ("SC01", "SC02", "SC03", "SC04", "SC05"):
        bundle = catalog.scenario_bundle(scenario)
        assert bundle["scenario"]["场景编码"] == scenario
        assert bundle["anomalies"], scenario
        assert bundle["problems"], scenario
        assert bundle["risks"], scenario
        assert bundle["causes"], scenario
        assert bundle["solutions"], scenario
        assert len(bundle["task_templates"]) == expected_tasks[scenario]
        assert bundle["actions"], scenario
        assert bundle["evidence_templates"], scenario
        assert bundle["verifications"], scenario


def test_bundle_is_scoped_to_its_own_problem() -> None:
    catalog = _catalog()
    sc01 = catalog.scenario_bundle("SC01")
    assert {row["code"] for row in sc01["solutions"]} == {"SL01", "SL02", "SL03", "SL04"}
    assert "SL08" not in {row["code"] for row in sc01["solutions"]}
    assert {row["code"] for row in sc01["causes"]} == {"CF01", "CF02", "CF03", "CF04"}
    sc05 = catalog.scenario_bundle("SC05")
    assert {row["code"] for row in sc05["solutions"]} == {"SL08"}
    assert {row["code"] for row in sc05["causes"]} == {"CF10", "CF11"}


def test_catalog_validation_has_no_errors() -> None:
    issues = _catalog().validate()
    assert [issue.to_dict() for issue in issues if issue.severity == "error"] == []


def test_dual_entry_search_returns_scenario_links() -> None:
    catalog = _catalog()
    metrics = catalog.search("超期未发")
    assert any(row["code"] == "M0143" for row in metrics)
    objects = catalog.search("订单")
    assert any(row["entryType"] == "businessObject" for row in objects)


def test_generated_catalog_records_source_hashes() -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    source = payload["source"]
    assert source["model"]["sha256"] == "8ee68d1e357d55930b2c9292c20ad582e4ed10745367ebfba19ce232f4e4a344"
    assert source["design"]["sha256"] == "a00558c3ef270d8b65567bb34800955666e6931d48b6a2bc94d1eeb3a2265da2"
    assert not list((ROOT / "dataset" / "process360").rglob("*.xlsx"))
    assert not list((ROOT / "dataset" / "process360").rglob("*.docx"))
