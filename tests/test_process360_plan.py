from __future__ import annotations

from pathlib import Path

from bi_agent.process360.catalog import Process360Catalog
from bi_agent.process360.service import Process360Service
from bi_agent.process360.store import Process360Store
from tests.test_process360_engine import FakeDB

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = {"tenantId": "t1", "userId": "u1", "canDispatch": True}


def service(tmp_path: Path) -> Process360Service:
    return Process360Service(
        catalog=Process360Catalog.from_project(ROOT),
        db=FakeDB(),
        store=Process360Store(tmp_path / "runtime.sqlite3"),
        cwd=ROOT,
    )


def test_composite_plan_has_dependencies_and_persisted_budget(tmp_path: Path) -> None:
    result = service(tmp_path).plan(
        question="本月超期未发为什么增加？",
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        principal=PRINCIPAL,
    )
    assert result["status"] == "ok"
    assert result["planId"]
    assert {step["sop"] for step in result["steps"]} >= {"P03", "P09"}
    assert any(step["dependsOn"] for step in result["steps"])
    saved = service(tmp_path).store.get_plan(result["planId"])
    assert saved["payload"]["budget"]["limit"]["calls"] >= 1


def test_exploration_rejects_tools_outside_plan_and_deduplicates_requests(tmp_path: Path) -> None:
    svc = service(tmp_path)
    planned = svc.plan(
        question="本月超期未发为什么增加",
        scenario="SC01",
        scope={"periodEnd": "2026-10-27"},
        principal=PRINCIPAL,
    )
    step = next(item for item in planned["steps"] if item["sop"] == "P03")
    denied = svc.explore(
        plan_id=planned["planId"],
        step_id=step["id"],
        tool="TaskOrderCreate",
        parameters={"scenario": "SC01"},
        principal=PRINCIPAL,
    )
    assert denied["status"] == "blocked"
    first = svc.explore(
        plan_id=planned["planId"], step_id=step["id"], tool="Process360Query",
        parameters={"scenario": "SC01"}, principal=PRINCIPAL,
    )
    second = svc.explore(
        plan_id=planned["planId"], step_id=step["id"], tool="Process360Query",
        parameters={"scenario": "SC01"}, principal=PRINCIPAL,
    )
    assert first["stage"] == "S03" and first["exploration"]["created"] is True
    assert second["exploration"]["created"] is False
    assert second["exploration"]["record"]["id"] == first["exploration"]["record"]["id"]
