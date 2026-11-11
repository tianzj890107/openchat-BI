"""Process360 orchestration: S00 -> S07 over the local catalog.

The service is UI/MCP agnostic.  It exposes one method per stage plus a
``closed_loop`` convenience that stops before execution.  It never accepts SQL
and never executes a business write from analysis; S06 is a separate call.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .analysis import analyze as analyze_stage
from .advanced import (
    compare_metrics,
    compare_solution_options,
    normalize_dimension,
    previous_period,
    process_conversion,
    progress_from_receipts,
    rule_forecast,
    structure_from_records,
    validate_solution_structure,
)
from .catalog import Process360Catalog
from .closure import build_baseline, build_closure, object_key
from .context import build_context, search as search_stage
from .db import DatabaseQueryError, DatabaseUnavailable, PostgresDatabase
from .evidence import apply_evidence
from .execute import send_task_order, _assert_task_no_phone
from .identity import PrincipalScope
from .models import Scope, combine_status, envelope, gap, dedupe_gaps
from .plans import build_draft
from .planner import TOOL_FOR_SOP, PlanExecutionError, build_plan, run_exploration_step
from .queries import run_scenario
from .request_context import active_request_context, current_or_resolve
from .router import delivery_requirement, route as route_stage
from .store import Process360Store, digest
from .verify import build_verification
from ..integrations.fuxi_todo import (
    make_source_todo_id,
    normalize_item_type,
    normalize_recipients,
)


DRAFT_TTL_SECONDS = 7 * 86400
QUERY_CONTRACT_VERSION = "process360.query.v2"
QUERY_TEMPLATE_VERSION = "process360.queries.v2"
TRUSTED_APPROVAL_STATES = {"approved", "host_click_authorized"}


def _action_delivery_steps(decision: Any, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure an action-delivery plan contains an executable Draft step."""

    del decision, steps
    # P10/P11/P12 are delivery intents, not render tools.  The server first
    # freezes an analysis run, then creates the trusted draft that backs every
    # action card.  Sending still waits for the user's click.
    return [
        {
            "id": "step-1",
            "sop": "P09",
            "title": "候选原因与分析运行",
            "tool": "Process360Analyze",
            "dependsOn": [],
            "status": "pending",
        },
        {
            "id": "step-2",
            "sop": "P11",
            "title": "任务草稿与依赖",
            "tool": "Process360Draft",
            "dependsOn": ["step-1"],
            "status": "pending",
        },
    ]


def _query_ttl_seconds() -> float:
    try:
        value = int(os.environ.get("PROCESS360_QUERY_TTL_SECONDS", "900"))
    except ValueError:
        value = 900
    return float(max(1, min(value, 7 * 86400)))


def _period_count(question: str) -> int:
    match = re.search(r"近\s*([0-9一二三四五六七八九十两]+)\s*个?月", str(question or ""))
    if not match:
        return 2
    raw = match.group(1)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    try:
        value = int(raw)
    except ValueError:
        value = mapping.get(raw, 2)
    return max(2, min(value, 12))


class Process360Service:
    def __init__(
        self,
        *,
        catalog: Process360Catalog | None = None,
        db: Any | None = None,
        cwd: str | Path | None = None,
        store: Process360Store | None = None,
    ) -> None:
        self._cwd = Path(cwd or Path.cwd())
        catalog_path = (os.environ.get("PROCESS360_CATALOG_PATH") or "").strip()
        self.catalog = catalog or Process360Catalog.from_project(
            self._cwd, path=catalog_path or None
        )
        self.db = db if db is not None else PostgresDatabase()
        self._store = store

    @property
    def store(self) -> Process360Store:
        if self._store is None:
            configured = (os.environ.get("PROCESS360_STORE_PATH") or "").strip()
            self._store = Process360Store(
                configured or self._cwd / "dataset" / "process360" / "runtime.sqlite3"
            )
        return self._store

    @staticmethod
    def _principal(payload: Mapping[str, Any] | None) -> PrincipalScope:
        """Resolve the caller identity on the server side.

        The MCP runtime injects a server-resolved principal for every tool
        call.  When a direct Python caller provides none, the configured POC
        principal is used - never a model-supplied or anonymous one.
        """
        if payload is not None:
            return PrincipalScope.from_payload(payload, required=True)
        context = active_request_context()
        if context is not None:
            return context.principal
        return PrincipalScope.poc()

    def _request_context(
        self,
        identity: PrincipalScope,
        *,
        surface: str = "service",
        request_id: str = "",
        conversation_id: str = "",
    ):
        active = active_request_context()
        if active is not None:
            return active
        return current_or_resolve(
            principal=identity,
            surface=surface,
            request_id=request_id or uuid.uuid4().hex,
            conversation_id=conversation_id,
        )

    def _catalog_hash(self) -> str:
        return digest({"catalogId": self.catalog_id, "version": self.catalog_version})

    def _source_connection(self) -> str:
        config = getattr(self.db, "config", None)
        if config is None:
            return "database:test"
        public = config.public_dict() if hasattr(config, "public_dict") else {}
        return (
            f"pg:{public.get('host') or 'configured'}:{public.get('port') or ''}/"
            f"{public.get('database') or ''}#{public.get('schema') or ''}"
        )

    @staticmethod
    def _scope_contract(scope: Mapping[str, Any] | None) -> dict[str, Any]:
        resolved = Scope.from_payload(scope)
        value = resolved.to_dict()
        value.pop("limit", None)
        return value

    @staticmethod
    def _principal_gap(message: str) -> dict[str, Any]:
        return gap(
            "PRINCIPAL_SCOPE_INVALID",
            "身份或授权范围无效",
            needed="由宿主注入可信 tenantId/userId 及允许的数据范围",
            impact=message or "拒绝业务取数",
            severity="blocking",
            source="host",
        )

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

    def route(
        self,
        question: str,
        *,
        scenario: str | None = None,
        plan_id: str = "",
        revise_reason: str = "",
        principal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """S00 routing that yields a stored, verifiable execution plan.

        A caller may revise an existing plan, but the revision is recorded with
        its reason instead of silently re-routing.
        """
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S00", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[self._principal_gap(str(exc))],
            )
        decision = route_stage(question, self.catalog, scenario=scenario)
        status = "needs_clarification" if decision.clarification and not decision.scenario else "ok"
        delivery = delivery_requirement(
            question, sop_id=decision.sop_id, intent=decision.intent
        )
        steps = [
            {
                "id": "step-1",
                "sop": decision.sop_id,
                "title": decision.sop_title,
                "tool": TOOL_FOR_SOP.get(decision.sop_id, decision.sop_id),
                "dependsOn": [],
                "status": "pending",
            }
        ]
        if delivery["required"]:
            steps = _action_delivery_steps(decision, steps)
        payload = {
            "question": question,
            "scenario": decision.scenario,
            "sopId": decision.sop_id,
            "route": decision.to_dict(),
            "steps": steps,
            "actionDeliveryRequired": bool(delivery["required"]),
            "deliveryKind": delivery["kind"],
            "delivery": delivery,
            "scope": identity.merge_scope(Scope.from_payload(None)).to_dict(),
            "tenant": identity.tenant_id,
            "principalKey": identity.key,
            "revision": 1,
            "revisedFrom": None,
            "reviseReason": "",
        }
        if plan_id:
            previous = self.store.get_plan(str(plan_id))
            if not previous:
                return envelope(
                    "S00", "needs_clarification",
                    catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=decision.scenario,
                    gaps=[gap(
                        "PLAN_NOT_FOUND", "计划引用不存在",
                        needed="重新调用 Process360Route 生成计划",
                        impact="未执行，避免无记录地绕过原路由",
                        severity="blocking", source="runtime",
                    )],
                )
            prior = dict(previous.get("payload") or {})
            if str(prior.get("principalKey") or "") not in {"", identity.key}:
                return envelope(
                    "S00", "needs_clarification",
                    catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=decision.scenario,
                    gaps=[self._principal_gap("计划不属于当前用户")],
                )
            payload.update(
                revision=int(prior.get("revision") or 1) + 1,
                revisedFrom=str(plan_id),
                reviseReason=str(revise_reason or "").strip(),
                originalScenario=prior.get("scenario"),
                originalSopId=prior.get("sopId"),
            )
        saved = self.store.save_plan(payload, status=status)
        return envelope(
            "S00",
            status,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=decision.scenario,
            question=question,
            next_steps=["S01/S02 检索并装配场景上下文"]
            if status == "ok"
            else list(decision.clarification),
            route=decision.to_dict(),
            planId=saved["id"],
            revision=payload["revision"],
            revisedFrom=payload["revisedFrom"],
            steps=payload["steps"],
            actionDeliveryRequired=payload["actionDeliveryRequired"],
            deliveryKind=payload["deliveryKind"],
            delivery=payload["delivery"],
            principalScope=identity.fingerprint(),
        )

    def validate_plan(
        self, plan_id: str, scenario: str, identity: PrincipalScope
    ) -> dict[str, Any] | None:
        """Return a blocking gap when a step does not follow its stored plan."""
        if not plan_id:
            return None
        record = self.store.get_plan(str(plan_id))
        if not record:
            return gap(
                "PLAN_NOT_FOUND", "计划引用不存在",
                needed="重新调用 Process360Route",
                impact="该步骤未执行", severity="blocking", source="runtime",
            )
        payload = dict(record.get("payload") or {})
        if str(payload.get("principalKey") or "") not in {"", identity.key}:
            return self._principal_gap("计划不属于当前用户")
        planned = str(payload.get("scenario") or "").upper()
        if planned and str(scenario or "").upper() and planned != str(scenario).upper():
            return gap(
                "PLAN_SCENARIO_MISMATCH", "步骤与计划场景不一致",
                needed=f"按计划场景 {planned} 执行，或用 Process360Route 记录修订理由",
                impact="该步骤未执行", severity="blocking", source="runtime",
            )
        return None

    def validate_plan_step(
        self,
        plan_id: str,
        step_id: str,
        tool: str,
        scenario: str,
        identity: PrincipalScope,
        *,
        scope: Mapping[str, Any] | None = None,
        require_plan: bool = False,
    ) -> dict[str, Any] | None:
        """Validate the complete plan/step contract before a business tool runs."""
        if not str(plan_id or "").strip():
            if not require_plan:
                return None
            return gap(
                "PLAN_REQUIRED",
                "缺少服务端执行计划",
                needed="先调用 Process360Route 或 Process360Plan 获取 planId",
                impact="业务步骤未执行，避免无计划取数或写操作",
                severity="blocking",
                source="runtime",
            )
        base = self.validate_plan(plan_id, scenario, identity)
        if base:
            return base
        record = self.store.get_plan(str(plan_id)) or {}
        payload = dict(record.get("payload") or {})
        clarifications = payload.get("clarification") or (payload.get("route") or {}).get("clarification") or []
        if payload.get("status") == "needs_clarification" or clarifications:
            return gap(
                "PLAN_CLARIFICATION_PENDING",
                "执行计划仍有影响结果的澄清项",
                needed="先向用户确认计划中的场景、范围或口径，再生成修订计划",
                impact="业务步骤未执行，避免按假设取数",
                severity="blocking",
                source="runtime",
            )
        steps = list(payload.get("steps") or [])
        if not str(step_id or "").strip():
            return gap(
                "PLAN_STEP_REQUIRED",
                "缺少计划步骤引用",
                needed="传入计划 steps[] 中的 stepId",
                impact="业务步骤未执行，避免绕过步骤约束",
                severity="blocking",
                source="runtime",
            )
        if not steps:
            return gap(
                "PLAN_STEP_NOT_FOUND",
                "计划没有可执行步骤",
                needed="重新调用 Process360Plan 生成带步骤的计划",
                impact="业务步骤未执行",
                severity="blocking",
                source="runtime",
            )
        step = next((item for item in steps if str(item.get("id") or "") == str(step_id)), None)
        if not step:
            return gap(
                "PLAN_STEP_NOT_FOUND",
                "步骤不属于该计划",
                needed="使用当前计划中的 stepId",
                impact="业务步骤未执行",
                severity="blocking",
                source="runtime",
            )
        expected_tool = str(step.get("tool") or "")
        if expected_tool and expected_tool != str(tool):
            return gap(
                "PLAN_TOOL_MISMATCH",
                "工具与计划步骤不匹配",
                needed=f"该步骤只允许调用 {expected_tool}",
                impact=f"{tool} 未执行",
                severity="blocking",
                source="runtime",
            )
        latest_steps = {
            str(item.get("step_id") or ""): item
            for item in self.store.list_plan_steps(str(plan_id))
            if item.get("step_id")
        }
        completed = {
            step
            for step, item in latest_steps.items()
            if str(item.get("status") or "") in {"completed", "succeeded", "ok", "partial"}
        }
        pending_dependencies = [
            f"{item}({latest_steps.get(str(item), {}).get('status') or 'pending'})"
            for item in (step.get("dependsOn") or [])
            if str(item) not in completed
        ]
        if pending_dependencies:
            return gap(
                "PLAN_DEPENDENCY_PENDING",
                "前置步骤尚未完成",
                needed="先完成计划步骤：" + "、".join(pending_dependencies),
                impact=f"{tool} 未执行",
                severity="blocking",
                source="runtime",
            )
        plan_scope = payload.get("scope") if isinstance(payload.get("scope"), Mapping) else None
        if scope is not None and plan_scope is not None:
            try:
                requested = identity.merge_scope(Scope.from_payload(scope)).to_dict()
                planned = identity.merge_scope(Scope.from_payload(plan_scope)).to_dict()
            except ValueError:
                requested = dict(scope or {})
                planned = dict(plan_scope or {})
            if requested != planned:
                return gap(
                    "PLAN_SCOPE_MISMATCH",
                    "查询范围与计划不一致",
                    needed="使用计划 scope，或先生成带修订理由的新计划",
                    impact=f"{tool} 未执行，避免换范围复用结论",
                    severity="blocking",
                    source="runtime",
                )
        return None

    def search(self, query: str, *, scenario: str | None = None, limit: int = 20) -> dict[str, Any]:
        return search_stage(self.catalog, query, scenario=scenario, limit=limit)

    def context(self, scenario: str, *, question: str | None = None) -> dict[str, Any]:
        return build_context(self.catalog, scenario, question=question)

    # -- S03 --------------------------------------------------------------
    def _blocked_query(
        self, scenario: str, scope: Scope, message: str, code: str = "DATABASE_UNAVAILABLE"
    ) -> dict[str, Any]:
        return envelope(
            "S03",
            "blocked",
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=scenario,
            scope=scope,
            dataSource="process360-postgres",
            sourceConnection=self._source_connection(),
            gaps=[
                gap(
                    code,
                    "业务事实库不可用",
                    needed="配置只读 PostgreSQL 连接并确认表结构",
                    impact="本场景指标无法取数；不补 0",
                    severity="blocking",
                    source="runtime",
                )
            ],
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

    def _query_full(
        self,
        scenario: str,
        *,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        plan_id: str = "",
    ) -> dict[str, Any]:
        """Execute (or reuse) one controlled query and keep the full rows."""
        code = str(scenario or "").strip().upper()
        try:
            identity = self._principal(principal)
            resolved = identity.merge_scope(Scope.from_payload(scope))
        except ValueError as exc:
            return envelope(
                "S03",
                "needs_clarification",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=code or None,
                next_steps=[str(exc)],
                limitations=["范围参数不合法，未执行数据库查询。"],
                gaps=[self._principal_gap(str(exc))] if principal is not None else [],
                principalScope=identity.fingerprint() if "identity" in locals() else None,
            )
        plan_gap = self.validate_plan(plan_id, code, identity)
        if plan_gap:
            return envelope(
                "S03", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=code or None,
                scope=resolved, gaps=[plan_gap],
                limitations=["计划校验未通过，未执行数据库查询。"],
            )
        ready, reason = self._db_ready()
        if not ready:
            return self._blocked_query(code, resolved, reason)
        try:
            result = self._run_scenario_snapshot(code, resolved)
            result = self._stamp_query_source(result, resolved)
            result["principalScope"] = identity.fingerprint()
            result["requestedScope"] = dict(scope or {})
            return self._remember_query(code, identity, result)
        except DatabaseUnavailable as exc:
            result = self._blocked_query(code, resolved, str(exc))
            result["principalScope"] = identity.fingerprint()
            return result
        except DatabaseQueryError as exc:
            result = self._blocked_query(code, resolved, str(exc), code="DATABASE_QUERY_FAILED")
            result["principalScope"] = identity.fingerprint()
            return result
        except ValueError as exc:
            result = envelope(
                "S03",
                "not_applicable",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=code or None,
                scope=resolved,
                limitations=[str(exc)],
            )
            return self._stamp_query_source(result, resolved)

    def _stamp_query_source(
        self, result: dict[str, Any], scope: Scope | None = None
    ) -> dict[str, Any]:
        """Keep provenance even when a governed calculation is blocked."""
        result["dataSource"] = "process360-postgres"
        result["sourceConnection"] = self._source_connection()
        if result.get("scope") is None and scope is not None:
            result["scope"] = scope.to_dict()
        return result

    def _run_scenario_snapshot(self, code: str, scope: Scope) -> dict[str, Any]:
        """Run display and full-object passes in one read-only snapshot."""
        snapshot = getattr(self.db, "snapshot", None)
        if callable(snapshot):
            with snapshot() as reader:
                return self._run_scenario_with_full_rows(code, scope, reader)
        return self._run_scenario_with_full_rows(code, scope, self.db)

    def _run_scenario_with_full_rows(self, code: str, scope: Scope, db: Any) -> dict[str, Any]:
        result = run_scenario(self.catalog, code, scope, db)
        if result.get("status") in {"blocked", "not_applicable", "needs_clarification"}:
            result["_fullRows"] = []
            return result
        info = dict(result.get("queryInfo") or {})
        rows = list(result.get("records") or [])
        total = int(info.get("totalRows") or 0)
        full_rows = rows
        if total > len(rows) or info.get("truncated"):
            limit = min(max(total, len(rows)), self.FREEZE_ROW_LIMIT)
            try:
                full = run_scenario(self.catalog, code, replace(scope, limit=limit), db)
                full_rows = list(full.get("records") or rows)
            except Exception:  # noqa: BLE001 - completeness is recorded as false
                full_rows = rows
        result["_fullRows"] = full_rows
        return result

    def _remember_query(
        self, code: str, identity: PrincipalScope, result: dict[str, Any]
    ) -> dict[str, Any]:
        """Store the full result server-side and stamp a reusable reference."""
        if result.get("status") in {"blocked", "not_applicable"}:
            result["queryId"] = None
            return result
        query_id = uuid.uuid4().hex
        full_rows = list(result.get("_fullRows") or result.get("records") or [])
        info = dict(result.get("queryInfo") or {})
        total = int(info.get("totalRows") or 0)
        keys = [object_key(row, code) for row in full_rows]
        unique_keys = [item for item in dict.fromkeys(keys) if item]
        complete = (
            (total == 0 and not full_rows)
            or (
                len(full_rows) >= total
                and len(unique_keys) == len(full_rows)
                and all(keys)
                and not info.get("truncated")
            )
        )
        result_hash = digest(
            {
                "scenario": code,
                "scope": result.get("scope") or {},
                "records": full_rows,
                "metrics": result.get("metrics") or [],
            }
        )
        expires_at = time.time() + _query_ttl_seconds()
        result["dataSource"] = "process360-postgres"
        result["sourceConnection"] = self._source_connection()
        self.store.save_query(
            scenario=code,
            scope=result.get("scope") or {},
            payload=result,
            tenant=identity.tenant_id,
            principal=identity.user_id,
            catalog_version=self.catalog_version,
            query_id=query_id,
            catalog_hash=self._catalog_hash(),
            authorization_version=identity.effective_authorization_version,
            grant_fingerprint=identity.grant_fingerprint,
            source_connection=self._source_connection(),
            template_version=QUERY_TEMPLATE_VERSION,
            result_hash=result_hash,
            complete=complete,
            full_count=len(full_rows),
            expires_at=expires_at,
            full_rows=full_rows,
            contract_version=QUERY_CONTRACT_VERSION,
        )
        result["queryId"] = query_id
        result["queryContract"] = {
            "version": QUERY_CONTRACT_VERSION,
            "complete": complete,
            "fullCount": len(full_rows),
            "expiresAt": expires_at,
            "authorizationVersion": identity.effective_authorization_version,
        }
        return result

    def _reuse_query(
        self,
        query_id: str,
        code: str,
        identity: PrincipalScope,
        *,
        requested_scope: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        stored = self.store.get_query(query_id)
        not_found = gap(
            "QUERY_NOT_FOUND_OR_INACCESSIBLE",
            "查询结果不存在或无权访问",
            needed="重新执行受控查询",
            impact="未复用旧结果，也没有用新范围静默替换",
            severity="blocking",
            source="runtime",
        )
        if (
            not stored
            or stored.get("tenant") != identity.tenant_id
            or stored.get("principal") != identity.user_id
        ):
            return None, not_found
        if stored.get("contract_version") != QUERY_CONTRACT_VERSION:
            return None, gap(
                "QUERY_LEGACY_CONTRACT",
                "旧查询记录没有完整授权与完整性契约",
                needed="重新执行查询生成 v2 查询结果",
                impact="旧结果不能作为可信复用或复验基准",
                severity="blocking",
                source="runtime",
            )
        if float(stored.get("expires_at") or 0) <= time.time():
            return None, gap(
                "QUERY_EXPIRED",
                "查询结果已超过有效期",
                needed="重新执行查询",
                impact="未复用过期结果",
                severity="blocking",
                source="runtime",
            )
        if (
            stored.get("authorization_version") != identity.effective_authorization_version
            or stored.get("grant_fingerprint") != identity.grant_fingerprint
        ):
            return None, gap(
                "QUERY_AUTHORIZATION_CHANGED",
                "授权版本或授权范围已变化",
                needed="按当前权限重新取数",
                impact="旧查询结果不再可读",
                severity="blocking",
                source="security",
            )
        if str(stored.get("source_connection") or "") != self._source_connection():
            return None, gap(
                "QUERY_SOURCE_CONNECTION_CHANGED",
                "查询结果的来源连接已变化",
                needed="按当前数据库连接重新取数",
                impact="未混用旧连接或旧快照的数据",
                severity="blocking",
                source="runtime",
            )
        if stored.get("catalog_version") and stored.get("catalog_version") != self.catalog_version:
            return None, gap(
                "QUERY_CATALOG_CHANGED",
                "本体目录版本已变化",
                needed="按当前本体版本重新取数",
                impact="未混用旧口径结果",
                severity="blocking",
                source="catalog",
            )
        if stored.get("catalog_hash") and stored.get("catalog_hash") != self._catalog_hash():
            return None, gap(
                "QUERY_CATALOG_CHANGED",
                "本体目录哈希已变化",
                needed="按当前本体版本重新取数",
                impact="未混用旧口径结果",
                severity="blocking",
                source="catalog",
            )
        if stored.get("template_version") != QUERY_TEMPLATE_VERSION:
            return None, gap(
                "QUERY_TEMPLATE_CHANGED",
                "查询模板版本不兼容",
                needed="使用当前查询模板重新取数",
                impact="未复用旧模板结果",
                severity="blocking",
                source="runtime",
            )
        if str(stored.get("scenario") or "").upper() != code:
            return None, gap(
                "QUERY_SCENARIO_MISMATCH",
                "查询结果与当前场景不一致",
                needed="重新执行当前场景查询",
                impact="未跨场景复用结果",
                severity="blocking",
                source="runtime",
            )
        if requested_scope is not None:
            requested = identity.merge_scope(Scope.from_payload(requested_scope))
            if self._scope_contract(requested.to_dict()) != self._scope_contract(stored.get("scope")):
                return None, gap(
                    "QUERY_SCOPE_CONFLICT",
                    "queryId 与本次查询范围不一致",
                    needed="去掉 queryId 重新查询，或使用同一范围",
                    impact="未用新范围覆盖原查询结果",
                    severity="blocking",
                    source="runtime",
                )
        payload = dict(stored.get("payload") or {})
        payload["queryId"] = stored.get("id")
        payload["queryReused"] = True
        payload["_fullRows"] = list(stored.get("full_rows") or [])
        return payload, None

    def _query_reference_error(self, code: str, query_id: str, issue: Mapping[str, Any]) -> dict[str, Any]:
        return envelope(
            "S03",
            "blocked",
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=code or None,
            queryId=query_id,
            gaps=[dict(issue)],
            limitations=["查询结果引用未通过授权、有效期或范围校验；未重新取数。"],
        )

    def _query_full_for(
        self,
        scenario: str,
        *,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        query_id: str = "",
        plan_id: str = "",
    ) -> dict[str, Any]:
        """Reuse a stored query when allowed, otherwise query once."""
        code = str(scenario or "").strip().upper()
        if query_id:
            try:
                identity = self._principal(principal)
            except ValueError as exc:
                return envelope(
                    "S03", "needs_clarification", catalog_id=self.catalog_id,
                    catalog_version=self.catalog_version, scenario=code or None,
                    gaps=[self._principal_gap(str(exc))],
                )
            reused, issue = self._reuse_query(
                str(query_id), code, identity, requested_scope=scope
            )
            if issue is not None:
                return self._query_reference_error(code, str(query_id), issue)
            if reused is not None:
                return reused
        return self._query_full(code, scope=scope, principal=principal)

    #: Upper bound for one full-object freeze pass.  Larger result sets stay
    #: incomplete on purpose instead of being silently truncated.
    FREEZE_ROW_LIMIT = 200_000

    def _freeze_rows(
        self, code: str, scope: Scope, query: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Return the complete object rows, independent of the display limit."""
        info = dict(query.get("queryInfo") or {})
        total = int(info.get("totalRows") or 0)
        rows = list(query.get("records") or [])
        if query.get("_fullRows") is not None:
            return list(query.get("_fullRows") or [])
        if not total or (not info.get("truncated") and len(rows) >= total):
            return rows
        limit = min(total, self.FREEZE_ROW_LIMIT)
        if limit <= len(rows):
            return rows
        try:
            full = run_scenario(self.catalog, code, replace(scope, limit=limit), self.db)
        except Exception:  # noqa: BLE001 - keep the partial set; completeness fails
            return rows
        return list(full.get("records") or rows)

    @staticmethod
    def compact_query(payload: Mapping[str, Any], *, sample: int = 5) -> dict[str, Any]:
        """Model-facing view: summary plus a bounded sample and a reference."""
        out = dict(payload)
        out.pop("_fullRows", None)
        rows = list(out.pop("records", []) or [])
        sample_rows = rows[: max(0, sample)]
        out["sampleRecords"] = sample_rows
        info = dict(out.get("queryInfo") or {})
        out["recordsRef"] = {
            "queryId": out.get("queryId"),
            "rowCount": len(rows),
            "totalRows": info.get("totalRows"),
            "sampleSize": len(sample_rows),
            "truncated": bool(info.get("truncated")),
        }
        evidence_items = []
        for item in out.get("evidence", []) or []:
            entry = dict(item)
            records = list(entry.pop("records", []) or [])
            entry["recordCount"] = len(records)
            entry["sampleRecords"] = records[:2]
            evidence_items.append(entry)
        out["evidence"] = evidence_items
        return out

    def query(
        self,
        scenario: str,
        *,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        query_id: str = "",
        sample: int = 5,
        plan_id: str = "",
    ) -> dict[str, Any]:
        """S03 tool entry: reuse a stored query or run one, then return a summary."""
        code = str(scenario or "").strip().upper()
        if query_id:
            try:
                identity = self._principal(principal)
            except ValueError as exc:
                return envelope(
                    "S03", "needs_clarification", catalog_id=self.catalog_id,
                    catalog_version=self.catalog_version, scenario=code or None,
                    gaps=[self._principal_gap(str(exc))],
                )
            reused, issue = self._reuse_query(
                str(query_id), code, identity, requested_scope=scope
            )
            if issue is not None:
                return self._query_reference_error(code, str(query_id), issue)
            if reused is not None:
                return self.compact_query(reused, sample=sample)
        full = self._query_full(code, scope=scope, principal=principal, plan_id=plan_id)
        return self.compact_query(full, sample=sample)

    # -- S04 --------------------------------------------------------------
    def _unsupported_analysis(self, decision, question: str):
        unsupported = {"P01", "P02", "P12", "P13", "P15"}
        if decision.sop_id not in unsupported:
            return None
        return envelope(
            "S04",
            "not_applicable",
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=decision.scenario,
            question=question,
            route=decision.to_dict(),
            gaps=[
                gap(
                    "SOP_EXECUTION_NOT_SUPPORTED",
                    "此 SOP 不能由单场景分析链完成",
                    needed="按路由调用对应专用工具；多期比较、流程转化、进度、预测和综合编排尚未实现",
                    impact="未取数、未生成风险或任务草稿",
                    source="runtime",
                )
            ],
            next_steps=[
                "P01/P02 使用检索与上下文；P12 经用户点击调用 TaskOrderCreate；P15 使用 Process360Verify",
                "P13 业务写入不在本服务执行范围；其余能力见验收未完成清单",
            ],
        )

    def plan(
        self,
        *,
        question: str,
        scenario: str | None = None,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        budget: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
            resolved = identity.merge_scope(Scope.from_payload(scope))
        except ValueError as exc:
            return envelope(
                "S00", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[self._principal_gap(str(exc))],
            )
        result = build_plan(
            self.catalog,
            question=question,
            scenario=scenario,
            scope=resolved,
            principal=identity.fingerprint(),
            budget=budget,
        )
        saved = self.store.save_plan(result, status=str(result.get("status") or "planned"))
        result["id"] = saved["id"]
        result["planId"] = saved["id"]
        result["principalScope"] = identity.fingerprint()
        return result

    def compare_periods(
        self,
        scenario: str,
        *,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        periods: int = 2,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
            current_scope = identity.merge_scope(Scope.from_payload(scope))
            previous_scope, previous_window = previous_period(current_scope)
        except ValueError as exc:
            return envelope(
                "S03", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=str(scenario or "").upper() or None,
                gaps=[self._principal_gap(str(exc))],
            )
        count = max(2, min(int(periods or 2), 12))
        windows = [current_scope]
        cursor = current_scope
        for _ in range(count - 1):
            cursor, _meta = previous_period(cursor)
            windows.append(cursor)
        queries = [
            self._query_full(scenario, scope=window.to_dict(), principal=principal)
            for window in windows
        ]
        current_query, previous_query = queries[0], queries[1]
        comparison = compare_metrics(current_query, previous_query)
        series = []
        for window, query in reversed(list(zip(windows, queries))):
            metrics = {
                str(item.get("code")): item.get("value")
                for item in query.get("metrics", [])
                if item.get("status") != "blocked"
            }
            series.append(
                {
                    "periodStart": window.period_start.isoformat() if window.period_start else None,
                    "periodEnd": window.observation_cutoff().isoformat(),
                    "status": query.get("status"),
                    "metrics": metrics,
                }
            )
        status = combine_status(
            [*(str(query.get("status")) for query in queries), comparison["status"]]
        )
        gaps = dedupe_gaps([gap_item for query in queries for gap_item in query.get("gaps", [])])
        return envelope(
            "S03",
            status,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper(),
            scope=current_scope,
            metrics=current_query.get("metrics", []),
            gaps=gaps,
            limitations=[
                "当前期与上一同长度期间分别取数；未结束期间不是完整同比/环比。",
                "零基期不计算增长率；阻断指标不补零。",
            ],
            comparison=comparison["rows"],
            series=series,
            periods=count,
            previousScope=previous_scope.to_dict(),
            previousWindow=previous_window,
            previousQuery={
                "status": previous_query.get("status"),
                "metrics": previous_query.get("metrics", []),
                "gaps": previous_query.get("gaps", []),
            },
            principalScope=identity.fingerprint(),
        )

    def structure(
        self,
        scenario: str,
        *,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        dimension: str = "",
        value_field: str = "",
        top_n: int = 10,
        query_id: str = "",
    ) -> dict[str, Any]:
        query = self._query_full_for(scenario, scope=scope, principal=principal, query_id=query_id)
        full_rows = list(query.get("_fullRows") or self._freeze_rows(
            str(scenario or "").upper(),
            Scope.from_payload(query.get("scope") or scope),
            query,
        ))
        total = int((query.get("queryInfo") or {}).get("totalRows") or 0)
        structure = structure_from_records(
            full_rows,
            dimension=normalize_dimension(dimension),
            value_field=value_field,
            top_n=top_n,
            truncated=bool(total and len(full_rows) < total),
        )
        status = combine_status([str(query.get("status")), str(structure.get("status"))])
        return envelope(
            "S03",
            status,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper(),
            scope=query.get("scope"),
            metrics=query.get("metrics", []),
            gaps=dedupe_gaps([*query.get("gaps", []), *structure.get("gaps", [])]),
            limitations=[*query.get("limitations", []), *structure.get("limitations", [])],
            structure=structure,
            queryId=query.get("queryId"),
            queryReused=bool(query.get("queryReused")),
            principalScope=query.get("principalScope"),
        )

    def process_flow(
        self,
        scenario: str,
        *,
        stages: Iterable[Mapping[str, Any]] | None = None,
        object_key: str = "objectId",
        batch_key: str = "batchId",
        principal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S03", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=str(scenario or "").upper() or None, gaps=[self._principal_gap(str(exc))],
            )
        result = process_conversion(stages, object_key=object_key, batch_key=batch_key)
        return envelope(
            "S03",
            str(result.get("status") or "blocked"),
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper() or None,
            gaps=result.get("gaps", []),
            limitations=result.get("limitations", []),
            processConversion=result,
            principalScope=identity.fingerprint(),
        )

    def progress(
        self,
        *,
        scenario: str | None = None,
        principal: Mapping[str, Any] | None = None,
        draft_id: str = "",
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S03", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=str(scenario or "").upper() or None, gaps=[self._principal_gap(str(exc))],
            )
        executions = []
        for item in self.store.list_executions(draft_id=draft_id):
            draft = self.store.get_draft(str(item.get("draft_id") or ""))
            if draft and draft.get("tenant") == identity.tenant_id and draft.get("principal") == identity.user_id:
                executions.append(item)
        receipts = [
            receipt
            for item in executions
            if (receipt := self.store.get_receipt(str(item.get("source_todo_id") or "")))
        ]
        result = progress_from_receipts(executions, receipts)
        return envelope(
            "S03",
            str(result.get("status") or "partial"),
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper() or None,
            limitations=result.get("limitations", []),
            tasks=result.get("tasks", []),
            receipts=result.get("receipts", []),
            principalScope=identity.fingerprint(),
        )

    def forecast(
        self,
        *,
        actual_to_date: float | None = None,
        target: float | None = None,
        elapsed_days: int | None = None,
        total_days: int | None = None,
        assumption: str = "",
        principal: Mapping[str, Any] | None = None,
        scenario: str | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
            result = rule_forecast(
                actual_to_date=actual_to_date,
                target=target,
                elapsed_days=elapsed_days,
                total_days=total_days,
                assumption=assumption,
            )
        except ValueError as exc:
            return envelope(
                "S04", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=str(scenario or "").upper() or None,
                gaps=[gap("FORECAST_INPUT_INVALID", "预测输入不合法", needed=str(exc), impact="未推算", source="runtime")],
            )
        return envelope(
            "S04",
            str(result.get("status") or "blocked"),
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper() or None,
            gaps=result.get("gaps", []),
            limitations=result.get("limitations", []),
            forecast=result,
            principalScope=identity.fingerprint(),
        )

    def review_solutions(
        self,
        *,
        tasks: Iterable[Mapping[str, Any]] | None = None,
        options: Iterable[Mapping[str, Any]] | None = None,
        due_at: str = "",
        principal: Mapping[str, Any] | None = None,
        scenario: str | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S05", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=str(scenario or "").upper() or None, gaps=[self._principal_gap(str(exc))],
            )
        structure = validate_solution_structure(tasks or [], due_at=due_at)
        comparison = compare_solution_options(options) if options else None
        gaps = [*structure.get("findings", []), *((comparison or {}).get("gaps") or [])]
        status = combine_status(
            [str(structure.get("status")), str((comparison or {}).get("status") or "ok")]
        )
        return envelope(
            "S05",
            status,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=str(scenario or "").upper() or None,
            gaps=gaps,
            solutionValidation=structure,
            solutionComparison=comparison,
            principalScope=identity.fingerprint(),
        )

    def explore(
        self,
        *,
        plan_id: str,
        step_id: str,
        tool: str,
        parameters: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S08", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[self._principal_gap(str(exc))],
            )
        saved = self.store.get_plan(plan_id)
        if not saved:
            return envelope(
                "S08", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[gap("PLAN_NOT_FOUND", "探索计划不存在", needed="先调用 Process360Plan", impact="未执行探索", severity="blocking", source="runtime")],
            )
        plan = dict(saved.get("payload") or {})
        plan["id"] = plan_id
        params = dict(parameters or {})
        params["principal"] = identity.to_dict()

        def execute_tool() -> dict[str, Any]:
            if tool == "Process360Query":
                return self._query_full(str(params.get("scenario") or ""), scope=params.get("scope"), principal=identity.to_dict())
            if tool == "Process360Analyze":
                return self.analyze(
                    question=str(params.get("question") or ""),
                    scenario=params.get("scenario"),
                    scope=params.get("scope"),
                    principal=identity.to_dict(),
                    evidence=params.get("evidence"),
                )
            if tool == "Process360Context":
                return self.context(str(params.get("scenario") or ""), question=params.get("question"))
            if tool == "Process360Search":
                return self.search(str(params.get("query") or ""), scenario=params.get("scenario"), limit=int(params.get("limit") or 20))
            if tool == "Process360Compare":
                return self.compare_periods(
                    str(params.get("scenario") or plan.get("scenario") or ""),
                    scope=params.get("scope"),
                    principal=identity.to_dict(),
                )
            if tool == "Process360Structure":
                return self.structure(
                    str(params.get("scenario") or plan.get("scenario") or ""),
                    scope=params.get("scope"),
                    principal=identity.to_dict(),
                    dimension=str(params.get("dimension") or ""),
                    value_field=str(params.get("valueField") or ""),
                    top_n=int(params.get("topN") or 10),
                )
            if tool == "Process360ProcessFlow":
                return self.process_flow(
                    str(params.get("scenario") or plan.get("scenario") or ""),
                    stages=params.get("stages"),
                    principal=identity.to_dict(),
                )
            if tool == "Process360Progress":
                return self.progress(
                    scenario=params.get("scenario") or plan.get("scenario"),
                    draft_id=str(params.get("draftId") or ""),
                    principal=identity.to_dict(),
                )
            if tool == "Process360Forecast":
                return self.forecast(
                    actual_to_date=params.get("actualToDate"),
                    target=params.get("target"),
                    elapsed_days=params.get("elapsedDays"),
                    total_days=params.get("totalDays"),
                    assumption=str(params.get("assumption") or ""),
                    scenario=params.get("scenario") or plan.get("scenario"),
                    principal=identity.to_dict(),
                )
            raise PlanExecutionError("unsupported exploration tool")

        try:
            outcome = run_exploration_step(
                plan=plan,
                step_id=step_id,
                tool=tool,
                request_hash=digest(params),
                executor=execute_tool,
                store=self.store,
                principal=identity.fingerprint(),
            )
        except (PlanExecutionError, ValueError) as exc:
            return envelope(
                "S08", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[gap("EXPLORATION_REJECTED", "探索调用被服务端拒绝", needed=str(exc), impact="未执行或未交付结果", severity="blocking", source="runtime")],
                planId=plan_id,
                stepId=step_id,
            )
        result = dict(outcome.get("result") or {})
        result.update(
            planId=plan_id,
            stepId=step_id,
            exploration=outcome,
            principalScope=identity.fingerprint(),
        )
        return result

    def comprehensive(
        self,
        *,
        question: str,
        scenario: str | None = None,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        planned = self.plan(question=question, scenario=scenario, scope=scope, principal=principal)
        if planned.get("status") == "blocked" or not planned.get("scenario"):
            return planned
        code = str(planned["scenario"])
        branches: dict[str, Any] = {}
        for step in planned.get("steps", []):
            sop = step.get("sop")
            if sop == "P03":
                branches["fact"] = self._query_full(code, scope=scope, principal=principal)
            elif sop == "P04":
                branches["trend"] = self.compare_periods(code, scope=scope, principal=principal)
            elif sop == "P05":
                branches["structure"] = self.structure(code, scope=scope, principal=principal)
            elif sop == "P06":
                query = self._query_full(code, scope=scope, principal=principal)
                context = build_context(self.catalog, code, question=question)
                branches["anomaly"] = analyze_stage(
                    self.catalog, code, context, query, question=question
                )
        status = combine_status([str(item.get("status")) for item in branches.values()])
        gaps = dedupe_gaps([gap_item for item in branches.values() for gap_item in item.get("gaps", [])])
        return envelope(
            "S04",
            status,
            catalog_id=self.catalog_id,
            catalog_version=self.catalog_version,
            scenario=code,
            question=question,
            scope=scope,
            gaps=gaps,
            planId=planned.get("planId"),
            plan=planned,
            subgoals=branches,
            limitations=[
                "综合总览只执行只读子目标，不自动创建任务或业务写操作。",
                "每个子目标独立验收；局部 blocked 不伪装为整体完成。",
            ],
            principalScope=planned.get("principalScope"),
        )

    def analyze(
        self,
        *,
        question: str = "",
        scenario: str | None = None,
        scope: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        evidence: Iterable[Mapping[str, Any]] | None = None,
        forecast_inputs: Mapping[str, Any] | None = None,
        query_id: str = "",
        plan_id: str = "",
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S04",
                "blocked",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=str(scenario or "").upper() or None,
                gaps=[self._principal_gap(str(exc))],
                limitations=["缺少可信宿主身份，未取数、未分析。"],
            )
        decision = route_stage(question or "分析当前场景", self.catalog, scenario=scenario)
        plan_gap = self.validate_plan(plan_id, decision.scenario or str(scenario or ""), identity)
        if plan_gap:
            return envelope(
                "S04", "needs_clarification", catalog_id=self.catalog_id,
                catalog_version=self.catalog_version, scenario=decision.scenario,
                gaps=[plan_gap],
                limitations=["计划校验未通过，未取数、未分析。"],
            )
        unsupported = self._unsupported_analysis(decision, question)
        if unsupported is not None:
            return unsupported
        if decision.sop_id == "P18":
            return self.comprehensive(
                question=question or "经营情况怎么样，主要风险是什么",
                scenario=decision.scenario,
                scope=scope,
                principal=principal,
            )
        if decision.sop_id == "P04" and decision.scenario:
            return self.compare_periods(
                decision.scenario,
                scope=scope,
                principal=principal,
                periods=_period_count(question),
            )
        if decision.sop_id == "P05" and decision.scenario:
            return self.structure(decision.scenario, scope=scope, principal=principal)
        if decision.sop_id == "P07" and decision.scenario:
            return self.process_flow(decision.scenario, principal=principal)
        if decision.sop_id == "P14":
            return self.progress(scenario=decision.scenario, principal=principal)
        if decision.sop_id == "P17":
            values = dict(forecast_inputs or {})
            return self.forecast(
                actual_to_date=values.get("actualToDate"),
                target=values.get("target"),
                elapsed_days=values.get("elapsedDays"),
                total_days=values.get("totalDays"),
                assumption=str(values.get("assumption") or ""),
                principal=principal,
                scenario=decision.scenario,
            )
        if not decision.scenario:
            return envelope(
                "S04",
                "needs_clarification",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                question=question or None,
                next_steps=list(decision.clarification),
                route=decision.to_dict(),
            )
        ctx = (
            dict(context)
            if (
                context
                and context.get("scenario") == decision.scenario
                and context.get("catalogId") == self.catalog_id
                and context.get("catalogVersion") == self.catalog_version
            )
            else build_context(self.catalog, decision.scenario, question=question or None)
        )
        query = self._query_full_for(
            decision.scenario, scope=scope, principal=principal, query_id=query_id, plan_id=plan_id
        )
        if query.get("status") == "needs_clarification" and any(
            item.get("code") == "PRINCIPAL_SCOPE_INVALID" for item in query.get("gaps", [])
        ):
            return query
        if query.get("status") == "needs_clarification":
            return {
                **query,
                "stage": "S04",
                "route": decision.to_dict(),
                "limitations": [
                    *query.get("limitations", []),
                    "范围或过滤条件未通过校验，未生成分析或任务草稿。",
                ],
            }
        resolved = Scope.from_payload(query.get("scope") or scope)
        full_rows = self._freeze_rows(decision.scenario, resolved, query)
        result = analyze_stage(
            self.catalog, decision.scenario, ctx, query, question=question or None
        )
        baseline = build_baseline(
            self.catalog,
            decision.scenario,
            resolved,
            query,
            principal=identity.fingerprint(),
            full_rows=full_rows,
        )
        compact = self.compact_query(query, sample=5)
        result["records"] = compact["sampleRecords"]
        result["recordsRef"] = compact["recordsRef"]
        result["queryId"] = query.get("queryId")
        run_id = uuid.uuid4().hex
        result = apply_evidence(
            self.catalog,
            result,
            list(evidence or []),
            run={"id": run_id, "payload": baseline},
        )
        result["route"] = decision.to_dict()
        result["contextSummary"] = ctx.get("counts")
        result["contextRef"] = {
            "scenario": decision.scenario,
            "counts": ctx.get("counts"),
            "note": "完整流程/规则/证据模板保留在服务端 catalog，按需用 Process360Context 读取。",
        }
        metric_codes = {
            str(item.get("code")) for item in query.get("metrics", []) if item.get("code")
        }
        result["metricCatalog"] = [
            dict(row)
            for row in (ctx.get("metrics") or [])
            if str(row.get("指标编码") or row.get("code") or "") in metric_codes
        ]
        result["metricCatalogRef"] = {
            "codes": sorted(metric_codes),
            "note": "仅返回本轮相关指标定义；完整指标目录见 Process360Context。",
        }
        result["runId"] = run_id
        result["dataSnapshot"] = {
            "catalogId": self.catalog_id,
            "catalogVersion": self.catalog_version,
            "queryHash": baseline["queryHash"],
            "baselineHash": baseline["baselineHash"],
            "observationWindow": baseline["observationWindow"],
            "objectCount": baseline["objectCount"],
            "fullObjectCount": baseline.get("fullObjectCount"),
            "complete": baseline.get("complete"),
            "objectSetHash": baseline.get("objectSetHash"),
        }
        result["principalScope"] = identity.fingerprint()
        result["evidenceStatus"] = result.get("evidenceValidation", {}).get("status")
        result["stopReason"] = (
            "fact_or_evidence_gap"
            if result.get("status") in {"blocked", "needs_clarification", "not_applicable"}
            else "analysis_complete"
        )
        self.store.save_run(
            run_id=run_id,
            scenario=decision.scenario,
            payload={
                "baseline": baseline,
                "analysis": result,
                "query": {
                    "status": query.get("status"),
                    "scope": query.get("scope"),
                    "metrics": query.get("metrics", []),
                    "records": (query.get("records") or [])[:200],
                    "recordsRef": {
                        "queryId": query.get("queryId"),
                        "rowCount": len(query.get("records") or []),
                    },
                    "gaps": query.get("gaps", []),
                },
            },
            tenant=identity.tenant_id,
            principal=identity.user_id,
        )
        for item in result.get("evidenceValidation", {}).get("items", []):
            self.store.save_evidence(
                run_id=run_id,
                template_code=str(item.get("requiredTemplates", [""])[0] if item.get("requiredTemplates") else item.get("code") or ""),
                payload={"cause": item.get("code"), "checks": item.get("checks", [])},
                status=str(item.get("status") or "unverified"),
            )
        return result

    # -- S05 --------------------------------------------------------------
    def draft(
        self,
        *,
        question: str = "",
        scenario: str | None = None,
        scope: Mapping[str, Any] | None = None,
        analysis: Mapping[str, Any] | None = None,
        run_id: str = "",
        query_id: str = "",
        principal: Mapping[str, Any] | None = None,
        owner_ref: str = "",
        owner_name: str = "",
        due_at: str = "",
        severity: str | None = None,
        solutions: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S05",
                "blocked",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=str(scenario or "").upper() or None,
                gaps=[self._principal_gap(str(exc))],
                tasks=[],
                canvasActions=[],
                limitations=["缺少可信宿主身份，未生成草稿。"],
            )
        if analysis and (
            scenario
            and analysis.get("scenario") != str(scenario).upper()
            or analysis.get("catalogId") != self.catalog_id
            or analysis.get("catalogVersion") != self.catalog_version
            or query_id and analysis.get("queryId") and analysis.get("queryId") != query_id
        ):
            return envelope(
                "S05",
                "needs_clarification",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=scenario,
                gaps=[
                    gap(
                        "ANALYSIS_CONTEXT_MISMATCH",
                        "分析场景或本体版本不一致",
                        needed="使用当前场景与版本重新分析",
                        impact="未生成任务令",
                    )
                ],
                tasks=[],
                canvasActions=[],
            )
        supplied_run_id = str(run_id or (analysis or {}).get("runId") or "").strip()
        if supplied_run_id:
            run = self.store.get_run(supplied_run_id)
            if not run or run.get("tenant") != identity.tenant_id or run.get("principal") != identity.user_id:
                return envelope(
                    "S05",
                    "blocked",
                    catalog_id=self.catalog_id,
                    catalog_version=self.catalog_version,
                    scenario=scenario,
                    gaps=[self._principal_gap("runId 不存在或不属于当前用户")],
                    tasks=[],
                    canvasActions=[],
                )
            result = dict((run.get("payload") or {}).get("analysis") or {})
            run_query = ((run.get("payload") or {}).get("query") or {})
            run_query_id = str(
                (run_query.get("recordsRef") or {}).get("queryId")
                or run_query.get("queryId")
                or result.get("queryId")
                or ""
            )
            if query_id and run_query_id != str(query_id):
                return envelope(
                    "S05",
                    "needs_clarification",
                    catalog_id=self.catalog_id,
                    catalog_version=self.catalog_version,
                    scenario=scenario,
                    gaps=[gap("ANALYSIS_QUERY_MISMATCH", "分析运行不是基于指定查询结果", needed="使用该 queryId 重新分析，或移除不匹配的 queryId", impact="未生成任务令")],
                    tasks=[],
                    canvasActions=[],
                )
            if not result.get("runId"):
                result["runId"] = supplied_run_id
            if scenario and result.get("scenario") != str(scenario).upper():
                return envelope(
                    "S05",
                    "needs_clarification",
                    catalog_id=self.catalog_id,
                    catalog_version=self.catalog_version,
                    scenario=scenario,
                    gaps=[gap("ANALYSIS_CONTEXT_MISMATCH", "分析运行与场景不一致", needed="使用当前场景重新分析", impact="未生成任务令")],
                    tasks=[],
                    canvasActions=[],
                )
        elif analysis and analysis.get("scenario"):
            return envelope(
                "S05",
                "needs_clarification",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                scenario=scenario,
                gaps=[
                    gap(
                        "ANALYSIS_RUN_REQUIRED",
                        "任务草稿必须绑定服务端分析运行",
                        needed="先调用 Process360Analyze 并使用返回的 runId",
                        impact="不能使用模型或调用方自行拼装的分析结果生成任务令",
                    )
                ],
                tasks=[],
                canvasActions=[],
            )
        else:
            result = self.analyze(
                question=question,
                scenario=scenario,
                scope=scope,
                query_id=query_id,
                principal=principal,
            )
        code = str(result.get("scenario") or scenario or "").strip().upper()
        if not code:
            return envelope(
                "S05",
                "needs_clarification",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                question=question or None,
                next_steps=["先确认场景，再生成任务令草稿"],
            )
        ctx = build_context(self.catalog, code, question=question or None)
        output = build_draft(
            self.catalog,
            code,
            ctx,
            result,
            owner_ref=owner_ref,
            owner_name=owner_name,
            due_at=due_at,
            severity=severity,
            selected_solutions=list(solutions or []),
        )
        output["queryId"] = result.get("queryId") or (str(query_id) if query_id else None)
        risk_actions = list(output.get("riskActions") or [])
        task_actions = list(output.get("canvasActions") or [])
        if output.get("status") != "ok" or not (risk_actions or task_actions):
            output["runId"] = result.get("runId")
            output["principalScope"] = identity.fingerprint()
            output["approvalStatus"] = "not_available"
            return output
        draft_id = uuid.uuid4().hex
        approval_status = "host_click_authorized" if identity.can_dispatch else "pending"
        saved = self.store.save_draft(
            draft_id=draft_id,
            scenario=code,
            run_id=str(result.get("runId") or ""),
            tenant=identity.tenant_id,
            principal=identity.user_id,
            payload={
                "runId": result.get("runId"),
                "queryId": output.get("queryId"),
                "scenario": code,
                "tasks": output.get("tasks", []),
                "riskActions": risk_actions,
                "canvasActions": [*risk_actions, *task_actions],
            },
            approval_status=approval_status,
            ttl_seconds=DRAFT_TTL_SECONDS,
        )
        draft_hash = saved["hash"]
        # The host stores only these opaque references in the action card.  The
        # clicked tool reloads the trusted content from the server.
        refs = {
            "draftId": saved["id"],
            "draftHash": draft_hash,
            "runId": result.get("runId"),
            "queryId": output.get("queryId"),
            "actionId": "",
            "scenario": code,
            "approvalStatus": approval_status,
            "expiresAt": saved["expiresAt"],
            "dispatchTool": "",
        }
        dispatch_tools: set[str] = set()
        for action in [*risk_actions, *task_actions]:
            item_type = str(action.get("item_type") or action.get("itemType") or "TODO").upper()
            dispatch_tool = str(
                action.get("dispatchTool")
                or ("RiskItemCreate" if item_type == "RISK" else "TaskOrderCreate")
            )
            action.update({
                **refs,
                "item_type": item_type,
                "dispatchTool": dispatch_tool,
                "actionId": str(action.get("id") or ""),
            })
            metadata = action.get("metadata") if isinstance(action.get("metadata"), dict) else {}
            metadata["dispatchTool"] = dispatch_tool
            action["metadata"] = metadata
            dispatch_tools.add(dispatch_tool)
        for task in output.get("tasks", []):
            task.update({
                **refs,
                "item_type": "TODO",
                "dispatchTool": "TaskOrderCreate",
                "actionId": str(task.get("id") or ""),
            })
        primary_tool = (
            "TaskOrderCreate"
            if "TaskOrderCreate" in dispatch_tools
            else next(iter(dispatch_tools), "TaskOrderCreate")
        )
        output.update(
            draftId=saved["id"],
            draftHash=draft_hash,
            runId=result.get("runId"),
            queryId=output.get("queryId"),
            expiresAt=saved["expiresAt"],
            approvalStatus=approval_status,
            dispatchTool=primary_tool,
            dispatchTools=sorted(dispatch_tools),
            principalScope=identity.fingerprint(),
            limitations=[
                *output.get("limitations", []),
                "点击风险卡调用 RiskItemCreate，点击处置待办调用 TaskOrderCreate；两者都只携带草稿引用，内容以服务端草稿为准。",
                "风险卡只表达已观察风险，候选原因标为待验证；推送成功不代表风险解除。",
            ],
        )
        return output

    # -- S06 --------------------------------------------------------------
    def execute(
        self,
        *,
        task: Mapping[str, Any],
        recipients: Iterable[str] | str,
        action_id: str = "",
        canvas_id: str = "",
        source_todo_id: str | None = None,
        client: Any = None,
    ) -> dict[str, Any]:
        return send_task_order(
            self.catalog,
            task,
            recipients,
            action_id=action_id,
            canvas_id=canvas_id,
            source_todo_id=source_todo_id,
            client=client,
        )

    def execute_draft(
        self,
        *,
        draft_id: str,
        draft_hash: str,
        action_id: str,
        recipients: Iterable[str] | str,
        principal: Mapping[str, Any] | None = None,
        idempotency_key: str = "",
        recipient_hash: str = "",
        retry: bool = False,
        client: Any = None,
        source_updated_at: str = "",
        item_type: str = "",
    ) -> dict[str, Any]:
        """Create one Fuxi risk/todo item from a trusted suggestion-card draft."""
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S06",
                "blocked",
                catalog_id=self.catalog_id,
                catalog_version=self.catalog_version,
                gaps=[self._principal_gap(str(exc))],
                receipt=None,
            )
        draft = self.store.get_draft(draft_id)
        if not draft:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                gaps=[gap("DRAFT_NOT_FOUND", "任务草稿不存在", needed="重新生成并保存草稿", impact="未创建待办", severity="blocking", source="runtime")],
            )
        if draft.get("expired"):
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("DRAFT_EXPIRED", "任务草稿已过期", needed="重新分析并生成草稿", impact="未创建待办", severity="blocking", source="runtime")],
            )
        if draft.get("tenant") != identity.tenant_id or draft.get("principal") != identity.user_id:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[self._principal_gap("草稿不属于当前用户或租户")],
            )
        if not draft_hash or str(draft_hash) != str(draft.get("payload_hash") or ""):
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("DRAFT_HASH_MISMATCH", "草稿签名不一致", needed="重新生成建议卡并使用最新 draftHash", impact="未创建待办", severity="blocking", source="runtime")],
            )
        action = (draft.get("actions") or {}).get(str(action_id or ""))
        if not action:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("DRAFT_ACTION_NOT_FOUND", "建议不属于该草稿", needed="从当前建议卡选择 actionId", impact="未创建待办", severity="blocking", source="runtime")],
            )
        action_item_type = normalize_item_type(
            action.get("item_type") or action.get("itemType") or "TODO"
        )
        requested_item_type = (
            normalize_item_type(item_type) if str(item_type or "").strip() else action_item_type
        )
        if requested_item_type != action_item_type:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap(
                    "DISPATCH_ITEM_TYPE_MISMATCH",
                    "下发工具与卡片类型不一致",
                    needed=(
                        "风险卡使用 RiskItemCreate，处置待办使用 TaskOrderCreate"
                    ),
                    impact="未调用 Fuxi",
                    severity="blocking",
                    source="runtime",
                )],
                draftId=draft_id,
                actionId=action_id,
            )
        if not identity.can_dispatch:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("DISPATCH_NOT_AUTHORIZED", "当前用户无任务下发权限", needed="宿主授予 canDispatch 或交由有权限人员点击", impact="未创建待办", severity="blocking", source="host")],
            )
        approval = str(draft.get("approval_status") or "").upper()
        if approval.lower() not in TRUSTED_APPROVAL_STATES:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("DISPATCH_APPROVAL_REQUIRED", "草稿未获点击授权", needed="由可信宿主完成审批或点击授权", impact="未创建待办", severity="blocking", source="runtime")],
            )
        task = {
            "id": action.get("id") or action_id,
            "title": action.get("title"),
            "content": action.get("content"),
            "evidence": action.get("evidence"),
            "severity": action.get("severity"),
            "dueAt": action.get("due_at") or action.get("dueAt"),
            "ownerRef": action.get("owner_ref") or action.get("ownerRef"),
            "ownerName": action.get("owner_name") or action.get("ownerName"),
            "item_type": action_item_type,
            "category": action.get("category"),
            "scenario": action.get("scenario") or draft.get("scenario"),
            "solution": (action.get("metadata") or {}).get("solution"),
            "taskTemplate": action.get("task_template") or (action.get("metadata") or {}).get("taskTemplate"),
            "verification": (action.get("metadata") or {}).get("verification"),
            "riskCode": (action.get("metadata") or {}).get("riskCode"),
            "dataBoundary": (action.get("metadata") or {}).get("dataBoundary"),
            "severityBasis": action.get("severityBasis"),
            "dispatch": {"source": action.get("source") or "boulderai-anaylize-todo"},
        }
        try:
            _assert_task_no_phone(task)
        except ValueError as exc:
            return envelope(
                "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=draft.get("scenario"),
                gaps=[gap("PRIVATE_DATA_IN_TASK", "任务内容包含手机号", needed="任务正文不得包含手机号", impact="未创建待办", severity="blocking", source="runtime")],
                limitations=[str(exc)],
            )
        if not idempotency_key:
            from .dispatch import execution_key

            key = execution_key(identity.tenant_id, draft_id, action_id, action_item_type)
        else:
            key = str(idempotency_key).strip()
        source_todo_id = make_source_todo_id(action_id, draft_id, action_item_type)
        normalized_recipients = normalize_recipients(recipients)
        recipient_hash = recipient_hash or digest({"recipients": sorted(normalized_recipients)})
        source_updated_at = source_updated_at or datetime.fromtimestamp(
            float(draft.get("created_at") or time.time()), tz=timezone.utc
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        snapshot = {
            "draftId": draft_id,
            "draftHash": draft_hash,
            "actionId": action_id,
            "itemType": action_item_type,
            "scenario": draft.get("scenario"),
            "principal": identity.fingerprint(),
            "recipientHash": recipient_hash,
            "recipientVersion": (os.environ.get("PROCESS360_RECIPIENT_MAP_VERSION") or "").strip(),
            "sourceTodoId": source_todo_id,
            "sourceUpdatedAt": source_updated_at,
            "requestId": (active_request_context().request_id if active_request_context() else ""),
            "authorizationVersion": identity.effective_authorization_version,
        }
        existing = self.store.get_execution(key)
        if existing:
            previous_request = dict(existing.get("request") or {})
            if (
                previous_request.get("recipientHash")
                and previous_request.get("recipientHash") != recipient_hash
            ):
                return envelope(
                    "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=draft.get("scenario"),
                    gaps=[gap("RECIPIENT_MAPPING_CHANGED", "接收人映射已变化", needed="重新生成草稿并确认新的接收人版本", impact="未向新接收人发送，旧请求身份保持不变", severity="blocking", source="security")],
                    draftId=draft_id,
                    actionId=action_id,
                )
            if existing.get("response"):
                previous = dict(existing["response"])
                retryable = any(
                    item.get("code") in {
                        "FUXI_TODO_FAILED", "FUXI_TODO_REJECTED", "FUXI_TODO_UNKNOWN",
                    }
                    for item in previous.get("gaps", [])
                ) or str(previous.get("status") or "") == "unknown"
                if not (retry and retryable):
                    previous["idempotentReplay"] = True
                    return previous
                existing["response"] = None
                existing["status"] = "sending"
            elif not retry:
                return envelope(
                    "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=draft.get("scenario"),
                    gaps=[gap("DISPATCH_IN_PROGRESS", "该建议正在下发", needed="等待当前请求完成；如确认失败，再用同一 idempotency_key 和 retry=true 重试", impact="未重复创建待办", severity="blocking", source="runtime")],
                    draftId=draft_id,
                    actionId=action_id,
                )
            if retry:
                consumption = self.store.get_action_consumption(draft_id, action_id)
                if consumption is None and not self.store.consume_action(
                    draft_id, action_id, consumed_by=identity.key
                ):
                    return envelope(
                        "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                        scenario=draft.get("scenario"),
                        gaps=[gap("DRAFT_ACTION_ALREADY_CONSUMED", "该建议已执行", needed="使用原回执；不要用新的幂等键重复下发", impact="未重复创建待办", severity="blocking", source="runtime")],
                        draftId=draft_id,
                        actionId=action_id,
                    )
                if consumption is not None and str(consumption.get("consumed_by") or "") != identity.key:
                    return envelope(
                        "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                        scenario=draft.get("scenario"),
                        gaps=[gap("DRAFT_ACTION_ALREADY_CONSUMED", "该建议已由其他操作消费", needed="使用原发起人的回执重试", impact="未重复创建待办", severity="blocking", source="runtime")],
                        draftId=draft_id,
                        actionId=action_id,
                    )
            execution = existing
            source_todo_id = str(existing.get("source_todo_id") or source_todo_id)
            source_updated_at = str(previous_request.get("sourceUpdatedAt") or source_updated_at)
        else:
            try:
                outcome, execution = self.store.claim_execution(
                    draft_id=draft_id,
                    action_id=action_id,
                    idempotency_key=key,
                    source_todo_id=source_todo_id,
                    consumed_by=identity.key,
                    tenant=identity.tenant_id,
                    principal=identity.user_id,
                    request_id=active_request_context().request_id if active_request_context() else "",
                    authorization_version=identity.effective_authorization_version,
                    recipient_hash=recipient_hash,
                    request=snapshot,
                )
            except Exception as exc:  # noqa: BLE001 - never send without a durable claim
                return envelope(
                    "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=draft.get("scenario"),
                    gaps=[gap(
                        "EXECUTION_REGISTRATION_FAILED",
                        "执行登记失败",
                        needed="恢复运行记录存储后重试；不要换幂等键重新发送",
                        impact="未调用 Fuxi，未创建待办",
                        severity="blocking",
                        source="runtime",
                    )],
                    limitations=[f"durable execution claim failed: {type(exc).__name__}"],
                    draftId=draft_id,
                    actionId=action_id,
                )
            if outcome == "existing" and execution:
                if execution.get("response"):
                    replay = dict(execution["response"])
                    replay["idempotentReplay"] = True
                    return replay
                return envelope(
                    "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=draft.get("scenario"),
                    gaps=[gap("DISPATCH_IN_PROGRESS", "该建议正在下发", needed="等待当前执行完成", impact="未重复创建待办", severity="blocking", source="runtime")],
                    draftId=draft_id,
                    actionId=action_id,
                )
            if outcome == "consumed":
                return envelope(
                    "S06", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                    scenario=draft.get("scenario"),
                    gaps=[gap("DRAFT_ACTION_ALREADY_CONSUMED", "该建议已执行", needed="使用原回执；如失败请用同一幂等键重试", impact="未重复创建待办", severity="blocking", source="runtime")],
                    draftId=draft_id,
                    actionId=action_id,
                )
        result = send_task_order(
            self.catalog,
            task,
            normalized_recipients,
            action_id=action_id,
            canvas_id=draft_id,
            source_todo_id=source_todo_id,
            client=client,
            source_updated_at=source_updated_at,
        )
        result.update(
            draftId=draft_id,
            draftHash=draft_hash,
            actionId=action_id,
            itemType=action_item_type,
            runId=(draft.get("payload") or {}).get("runId"),
            executionId=execution.get("id"),
            idempotentReplay=False,
        )
        self.store.finish_execution(
            execution["id"],
            status={
                "ok": "succeeded",
                "unknown": "unknown",
                "rejected": "rejected",
            }.get(str(result.get("status") or ""), "blocked"),
            response=result,
        )
        receipt = result.get("receipt") if isinstance(result.get("receipt"), dict) else {}
        self.store.save_receipt(
            source_todo_id,
            status=str(result.get("status") or "blocked"),
            payload={
                "sourceTodoId": receipt.get("sourceTodoId") or source_todo_id,
                "batchRef": receipt.get("batchRef"),
                "applied": receipt.get("applied", 0),
                "skipped": receipt.get("skipped", 0),
                "errors": receipt.get("errors", []),
                "status": result.get("status"),
            },
        )
        return result

    # -- S07 --------------------------------------------------------------
    def verify(
        self,
        *,
        scenario: str,
        scope: Mapping[str, Any] | None = None,
        baseline: Mapping[str, Any] | None = None,
        run_id: str = "",
        principal: Mapping[str, Any] | None = None,
        approval_ref: str = "",
        approved_target: float | None = None,
        approved_direction: str = "",
        approved_minimum_denominator: int | None = None,
        excluded_object_keys: Iterable[str] | None = None,
        exclusion_evidence: Mapping[str, Any] | None = None,
        delivery_evidence: Mapping[str, Any] | None = None,
        query_id: str = "",
    ) -> dict[str, Any]:
        code = str(scenario or "").strip().upper()
        try:
            identity = self._principal(principal)
        except ValueError as exc:
            return envelope(
                "S07", "blocked", catalog_id=self.catalog_id, catalog_version=self.catalog_version,
                scenario=code, gaps=[self._principal_gap(str(exc))],
                closure={"status": "blocked", "canClose": False},
            )
        query = self._query_full_for(code, scope=scope, principal=principal, query_id=query_id)
        current = {
            str(item.get("code")): item.get("value")
            for item in query.get("metrics", [])
            if item.get("value") is not None and item.get("status") != "blocked"
        }
        legacy = build_verification(
            self.catalog,
            code,
            baseline={} if not run_id else baseline,
            current=current,
            delivery_evidence=delivery_evidence,
        )
        trusted_baseline = None
        extra_gaps: list[dict[str, Any]] = []
        approval_record: dict[str, Any] | None = None
        effective_target = approved_target
        effective_direction = approved_direction
        effective_minimum = approved_minimum_denominator
        if approval_ref.strip():
            approval_record = self.store.get_trusted_approval(
                approval_ref.strip(), tenant=identity.tenant_id
            )
            if not approval_record:
                extra_gaps.append(
                    gap(
                        "APPROVAL_NOT_FOUND",
                        "批准记录不存在或不属于当前租户",
                        needed="提供服务端可信批准记录编号",
                        impact="不采用调用方自填目标，不能判定达标",
                        severity="blocking",
                        source="security",
                    )
                )
                effective_target = None
                effective_direction = ""
                effective_minimum = None
            else:
                now = time.time()
                if str(approval_record.get("scenario") or "").upper() != code:
                    extra_gaps.append(
                        gap(
                            "APPROVAL_SCENARIO_MISMATCH",
                            "批准记录与复验场景不一致",
                            needed="使用同一场景的业务批准记录",
                            impact="不能跨场景复用目标",
                            severity="blocking",
                            source="security",
                        )
                    )
                if str(approval_record.get("status") or "").lower() != "approved":
                    extra_gaps.append(
                        gap(
                            "APPROVAL_NOT_ACTIVE",
                            "批准记录不是有效批准状态",
                            needed="由业务负责人完成批准",
                            impact="不能判定达标",
                            severity="blocking",
                            source="security",
                        )
                    )
                if float(approval_record.get("valid_from") or 0) > now:
                    extra_gaps.append(
                        gap(
                            "APPROVAL_NOT_YET_VALID",
                            "批准记录尚未生效",
                            needed="等待批准生效或使用当前有效批准",
                            impact="不能判定达标",
                            severity="blocking",
                            source="security",
                        )
                    )
                if float(approval_record.get("valid_until") or 0) < now:
                    extra_gaps.append(
                        gap(
                            "APPROVAL_EXPIRED",
                            "批准记录已过期",
                            needed="重新取得业务批准并保存新记录",
                            impact="不能判定达标",
                            severity="blocking",
                            source="security",
                        )
                    )
                stored_target = approval_record.get("target")
                if approved_target is not None and stored_target is not None:
                    try:
                        mismatched = abs(float(approved_target) - float(stored_target)) > 1e-9
                    except (TypeError, ValueError):
                        mismatched = True
                    if mismatched:
                        extra_gaps.append(
                            gap(
                                "APPROVAL_TARGET_MISMATCH",
                                "调用方目标与服务器批准记录不一致",
                                needed="以批准记录为准；模型或调用方不得覆盖目标",
                                impact="不采用调用方目标，不能判定达标",
                                severity="blocking",
                                source="security",
                            )
                        )
                stored_direction = str(approval_record.get("direction") or "").strip()
                if approved_direction and stored_direction and approved_direction != stored_direction:
                    extra_gaps.append(
                        gap(
                            "APPROVAL_DIRECTION_MISMATCH",
                            "调用方比较方向与批准记录不一致",
                            needed="以批准记录为准",
                            impact="不能判定达标",
                            severity="blocking",
                            source="security",
                        )
                    )
                effective_target = stored_target
                effective_direction = stored_direction
                effective_minimum = approval_record.get("minimum_denominator")
                approval_scope = (approval_record.get("payload") or {}).get("scope")
                if isinstance(approval_scope, Mapping) and approval_scope:
                    try:
                        requested = identity.merge_scope(Scope.from_payload(scope)).to_dict()
                        approved_scope = identity.merge_scope(Scope.from_payload(approval_scope)).to_dict()
                    except ValueError:
                        requested, approved_scope = dict(scope or {}), dict(approval_scope)
                    if requested != approved_scope:
                        extra_gaps.append(
                            gap(
                                "APPROVAL_SCOPE_MISMATCH",
                                "复验范围与批准范围不一致",
                                needed="按批准范围复验，或重新申请范围变更",
                                impact="不能判定达标",
                                severity="blocking",
                                source="security",
                            )
                        )
        elif approved_target is not None or approved_direction or approved_minimum_denominator is not None:
            extra_gaps.append(
                gap(
                    "UNTRUSTED_APPROVAL_REJECTED",
                    "拒绝调用方自填批准目标",
                    needed="提供服务端保存的 approvalRef",
                    impact="不采用模型目标，不能判定达标",
                    severity="blocking",
                    source="security",
                )
            )
            effective_target = None
            effective_direction = ""
            effective_minimum = None
        if run_id:
            run = self.store.get_run(run_id)
            if not run or run.get("tenant") != identity.tenant_id or run.get("principal") != identity.user_id:
                extra_gaps.append(
                    gap("VERIFICATION_RUN_NOT_FOUND", "冻结分析运行不存在或不属于当前用户", needed="使用本次分析返回的 runId", impact="不能判定效果", severity="blocking", source="runtime")
                )
            else:
                trusted_baseline = (run.get("payload") or {}).get("baseline")
                if not trusted_baseline or str(trusted_baseline.get("scenario") or "").upper() != code:
                    extra_gaps.append(
                        gap("VERIFICATION_BASELINE_MISMATCH", "冻结基准与复验场景不一致", needed="用同一场景重新分析以冻结基准", impact="不能跨场景复用基准", severity="blocking", source="runtime")
                    )
                    trusted_baseline = None
        else:
            extra_gaps.append(
                gap("VERIFICATION_BASELINE_MISSING", "缺少服务端冻结的原对象集合", needed="使用 Process360Analyze 返回的 runId", impact="调用方自填 baseline 不能作为可信基准", severity="blocking", source="runtime")
            )
            if baseline:
                extra_gaps.append(
                    gap("UNTRUSTED_BASELINE_REJECTED", "拒绝调用方自填基准", needed="改传 runId", impact="避免篡改原对象集合或分母", severity="blocking", source="security")
                )
        # Compare against the complete current object set, never the page sample.
        try:
            resolved_scope = Scope.from_payload(query.get("scope") or scope)
        except ValueError:
            resolved_scope = Scope.from_payload(None)
        current_rows = self._freeze_rows(code, resolved_scope, query)
        current_payload = dict(query)
        current_payload["records"] = current_rows
        result = build_closure(
            self.catalog,
            code,
            baseline=trusted_baseline,
            current=current_payload,
            approval_ref=approval_ref,
            approved_target=effective_target,
            approved_direction=effective_direction,
            approved_minimum_denominator=effective_minimum,
            excluded_keys=list(excluded_object_keys or []),
            exclusion_evidence=exclusion_evidence,
            delivery_evidence=delivery_evidence,
        )
        if effective_target is None:
            extra_gaps.append(
                gap("VERIFICATION_TARGET_MISSING", "复验目标尚未批准", needed="提供批准记录和批准目标值", impact="catalog 样例目标不启用", severity="blocking", source="runtime")
            )
        result["gaps"] = dedupe_gaps([*result["gaps"], *extra_gaps, *query.get("gaps", [])])
        if any(str(item.get("severity") or "") == "blocking" for item in extra_gaps):
            result["status"] = "blocked"
            if isinstance(result.get("closure"), dict):
                result["closure"]["canClose"] = False
                result["closure"]["status"] = "blocked"
        result["verification"] = legacy.get("verification")
        if approval_record:
            result["approval"] = {
                "approvalRef": approval_ref,
                "status": approval_record.get("status"),
                "target": approval_record.get("target"),
                "direction": approval_record.get("direction"),
                "minimumDenominator": approval_record.get("minimum_denominator"),
                "validFrom": approval_record.get("valid_from"),
                "validUntil": approval_record.get("valid_until"),
            }
        result["runId"] = run_id or None
        result["principalScope"] = identity.fingerprint()
        result["dataSnapshot"] = {
            "queryHash": (trusted_baseline or {}).get("queryHash"),
            "baselineHash": (trusted_baseline or {}).get("baselineHash"),
            "catalogVersion": self.catalog_version,
        }
        if query.get("status") in {"blocked", "needs_clarification", "not_applicable"}:
            result["status"] = query["status"]
            if result.get("verification"):
                result["verification"]["effect"]["status"] = "blocked"
            result["closure"] = {"status": "blocked", "canClose": False}
        result["currentQuery"] = {
            "status": query.get("status"),
            "scope": query.get("scope"),
            "metrics": query.get("metrics", []),
            "gaps": query.get("gaps", []),
            "limitations": query.get("limitations", []),
        }
        return result

    # -- convenience ------------------------------------------------------
    def closed_loop(
        self,
        *,
        question: str,
        scenario: str | None = None,
        scope: Mapping[str, Any] | None = None,
        principal: Mapping[str, Any] | None = None,
        owner_ref: str = "",
        owner_name: str = "",
        due_at: str = "",
    ) -> dict[str, Any]:
        decision = self.route(question, scenario=scenario)
        route_payload = decision.get("route") or {}
        code = route_payload.get("scenario")
        if decision.get("status") == "needs_clarification" or not code:
            return {
                **decision,
                "stages": {"S00": decision},
                "status": "needs_clarification",
            }
        unsupported = self._unsupported_analysis(
            route_stage(question, self.catalog, scenario=code), question
        )
        if unsupported is not None:
            return {**unsupported, "stages": {"S00": decision, "S04": unsupported}}
        if route_payload.get("sop") in {"P04", "P05", "P07", "P14", "P17", "P18"}:
            analysis = self.analyze(
                question=question, scenario=code, scope=scope, principal=principal
            )
            return {
                "schema": "process360.closed_loop.v1",
                "status": analysis.get("status"),
                "scenario": code,
                "catalogId": self.catalog_id,
                "catalogVersion": self.catalog_version,
                "stages": {"S00": decision, "S04": analysis},
                "analysis": analysis,
                "next": "按返回的子目标或缺口继续；不能把局部结果表述为全部完成。",
            }
        ctx = self.context(code, question=question)
        query = self._query_full(code, scope=scope, principal=principal)
        if route_payload.get("sop") == "P03":
            return {
                "schema": "process360.closed_loop.v1",
                "status": query["status"],
                "scenario": code,
                "catalogId": self.catalog_id,
                "catalogVersion": self.catalog_version,
                "stages": {"S00": decision, "S02": ctx, "S03": query},
                "next": "事实查询到此结束；只有明确要求才进入诊断或任务草稿。",
            }
        analysis = self.analyze(
            question=question, scenario=code, scope=scope, context=ctx, principal=principal
        )
        if route_payload.get("sop") != "P11":
            return {
                "schema": "process360.closed_loop.v1",
                "status": analysis["status"],
                "scenario": code,
                "catalogId": self.catalog_id,
                "catalogVersion": self.catalog_version,
                "stages": {"S00": decision, "S02": ctx, "S03": query, "S04": analysis},
                "analysis": analysis,
                "next": "分析结束；明确要求任务草稿后调用 Process360Draft。",
            }
        draft = self.draft(
            question=question,
            scenario=code,
            scope=scope,
            analysis=analysis,
            principal=principal,
            owner_ref=owner_ref,
            owner_name=owner_name,
            due_at=due_at,
        )
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
