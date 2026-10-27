"""Process360 orchestration: S00 -> S07 over the local catalog.

The service is UI/MCP agnostic.  It exposes one method per stage plus a
``closed_loop`` convenience that stops before execution.  It never accepts SQL
and never executes a business write from analysis; S06 is a separate call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from .analysis import analyze as analyze_stage
from .catalog import Process360Catalog
from .context import build_context, search as search_stage
from .db import DatabaseQueryError, DatabaseUnavailable, PostgresDatabase
from .execute import send_task_order
from .models import Scope, envelope, gap
from .plans import build_draft
from .queries import run_scenario
from .router import route as route_stage
from .verify import build_verification


class Process360Service:
    def __init__(self, *, catalog: Process360Catalog | None = None,
                 db: Any | None = None, cwd: str | Path | None = None) -> None:
        catalog_path = (os.environ.get("PROCESS360_CATALOG_PATH") or "").strip()
        self.catalog = catalog or Process360Catalog.from_project(
            cwd or Path.cwd(), path=catalog_path or None
        )
        self.db = db if db is not None else PostgresDatabase()

    # -- catalog ----------------------------------------------------------
    @property
    def catalog_id(self) -> str:
        return self.catalog.catalog_id

    @property
    def catalog_version(self) -> str:
        return self.catalog.version

    def info(self) -> dict[str, Any]:
        info = {
            "catalogId": self.catalog.catalog_id,
            "version": self.catalog.version,
            "summary": self.catalog.summary(),
        }
        if hasattr(self.db, "config") and hasattr(self.db.config, "public_dict"):
            info["database"] = self.db.config.public_dict()
        elif hasattr(self.db, "available"):
            info["database"] = {"configured": bool(self.db.available), "readOnly": True}
        else:
            info["database"] = {"configured": True, "readOnly": True}
        return info

    def route(self, question: str, *, scenario: str | None = None) -> dict[str, Any]:
        decision = route_stage(question, self.catalog, scenario=scenario)
        status = "needs_clarification" if decision.clarification and not decision.scenario else "ok"
        return envelope(
            "S00", status, catalog_id=self.catalog_id, catalog_version=self.catalog_version,
            scenario=decision.scenario, question=question,
            next_steps=["S01/S02 检索并装配场景上下文"] if status == "ok" else list(decision.clarification),
            route=decision.to_dict(),
        )

    def search(self, query: str, *, scenario: str | None = None, limit: int = 20) -> dict[str, Any]:
        return search_stage(self.catalog, query, scenario=scenario, limit=limit)

    def context(self, scenario: str, *, question: str | None = None) -> dict[str, Any]:
        return build_context(self.catalog, scenario, question=question)

    # -- S03 --------------------------------------------------------------
    def _blocked_query(self, scenario: str, scope: Scope, message: str, code: str = "DATABASE_UNAVAILABLE") -> dict[str, Any]:
        return envelope(
            "S03", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
            scenario=scenario, scope=scope,
            gaps=[gap(code, "业务事实库不可用", needed="配置只读 PostgreSQL 连接并确认表结构",
                      impact="本场景指标无法取数；不补 0", severity="blocking", source="runtime")],
            limitations=[message],
            next_steps=["配置 PROCESS360_PG_* 只读连接", "确认 LE000011/13/14/31 等视图可读"],
        )

    def _db_ready(self) -> tuple[bool, str]:
        ready = getattr(self.db, "available", None)
        if ready is None:
            return True, ""
        if callable(ready):
            return bool(ready()), ""
        if not ready:
            reason = getattr(self.db, "unavailable_reason", lambda: "只读数据库未配置")()
            return False, str(reason)
        return True, ""

    def query(self, scenario: str, *, scope: Mapping[str, Any] | None = None) -> dict[str, Any]:
        code = str(scenario or "").strip().upper()
        try:
            resolved = Scope.from_payload(scope)
        except ValueError as exc:
            return envelope(
                "S03", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=code or None,
                next_steps=[str(exc)],
                limitations=["范围参数不合法，未执行数据库查询。"],
            )
        ready, reason = self._db_ready()
        if not ready:
            return self._blocked_query(code, resolved, reason)
        try:
            return run_scenario(self.catalog, code, resolved, self.db)
        except (DatabaseUnavailable, DatabaseQueryError) as exc:
            return self._blocked_query(code, resolved, str(exc))
        except ValueError as exc:
            return envelope(
                "S03", "not_applicable", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=code or None,
                limitations=[str(exc)],
            )

    # -- S04 --------------------------------------------------------------
    def analyze(self, *, question: str = "", scenario: str | None = None,
                scope: Mapping[str, Any] | None = None,
                context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        decision = route_stage(question or "分析当前场景", self.catalog, scenario=scenario)
        if not decision.scenario:
            return envelope(
                "S04", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, question=question or None,
                next_steps=list(decision.clarification),
                route=decision.to_dict(),
            )
        ctx = dict(context) if context and context.get("scenario") == decision.scenario else build_context(
            self.catalog, decision.scenario, question=question or None
        )
        query = self.query(decision.scenario, scope=scope)
        result = analyze_stage(self.catalog, decision.scenario, ctx, query, question=question or None)
        result["route"] = decision.to_dict()
        result["contextSummary"] = ctx.get("counts")
        result["metricCatalog"] = ctx.get("metrics")
        return result

    # -- S05 --------------------------------------------------------------
    def draft(self, *, question: str = "", scenario: str | None = None,
              scope: Mapping[str, Any] | None = None,
              analysis: Mapping[str, Any] | None = None,
              owner_ref: str = "", owner_name: str = "",
              due_at: str = "", severity: str | None = None,
              solutions: Iterable[str] | None = None) -> dict[str, Any]:
        result = dict(analysis) if analysis and analysis.get("scenario") else self.analyze(
            question=question, scenario=scenario, scope=scope
        )
        code = str(result.get("scenario") or scenario or "").strip().upper()
        if not code:
            return envelope(
                "S05", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, question=question or None,
                next_steps=["先确认场景，再生成任务令草稿"],
            )
        if result.get("status") == "needs_clarification":
            return result
        ctx = build_context(self.catalog, code, question=question or None)
        return build_draft(
            self.catalog, code, ctx, result, owner_ref=owner_ref, owner_name=owner_name,
            due_at=due_at, severity=severity, selected_solutions=list(solutions or []),
        )

    # -- S06 --------------------------------------------------------------
    def execute(self, *, task: Mapping[str, Any], recipients: Iterable[str] | str,
                action_id: str = "", canvas_id: str = "",
                source_todo_id: str | None = None, client: Any = None) -> dict[str, Any]:
        return send_task_order(
            self.catalog, task, recipients, action_id=action_id, canvas_id=canvas_id,
            source_todo_id=source_todo_id, client=client,
        )

    # -- S07 --------------------------------------------------------------
    def verify(self, *, scenario: str, scope: Mapping[str, Any] | None = None,
               baseline: Mapping[str, Any] | None = None,
               delivery_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
        code = str(scenario or "").strip().upper()
        query = self.query(code, scope=scope)
        current = {
            str(item.get("code")): item.get("value")
            for item in query.get("metrics", [])
            if item.get("value") is not None and item.get("status") != "blocked"
        }
        result = build_verification(
            self.catalog, code, baseline=baseline, current=current,
            delivery_evidence=delivery_evidence,
        )
        result["currentQuery"] = {
            "status": query.get("status"),
            "scope": query.get("scope"),
            "metrics": query.get("metrics", []),
            "gaps": query.get("gaps", []),
            "limitations": query.get("limitations", []),
        }
        return result

    # -- convenience ------------------------------------------------------
    def closed_loop(self, *, question: str, scenario: str | None = None,
                    scope: Mapping[str, Any] | None = None,
                    owner_ref: str = "", owner_name: str = "",
                    due_at: str = "") -> dict[str, Any]:
        decision = self.route(question, scenario=scenario)
        route_payload = decision.get("route") or {}
        code = route_payload.get("scenario")
        if decision.get("status") == "needs_clarification" or not code:
            return {
                **decision,
                "stages": {"S00": decision},
                "status": "needs_clarification",
            }
        ctx = self.context(code, question=question)
        query = self.query(code, scope=scope)
        analysis = analyze_stage(self.catalog, code, ctx, query, question=question)
        analysis["route"] = route_payload
        draft = self.draft(question=question, scenario=code, scope=scope, analysis=analysis,
                           owner_ref=owner_ref, owner_name=owner_name, due_at=due_at)
        return {
            "schema": "process360.closed_loop.v1",
            "status": analysis.get("status"),
            "scenario": code,
            "catalogId": self.catalog_id,
            "catalogVersion": self.catalog_version,
            "stages": {"S00": decision, "S02": ctx, "S03": query, "S04": analysis, "S05": draft},
            "analysis": analysis,
            "draft": draft,
            "next": "S06 仅在用户点击时由 Fuxi 宿主调用 TaskOrderCreate；S07 需复验基准与 RF 目标",
        }
