"""MCP-facing Process360 tool catalog.

The tools expose the deterministic engine only.  There is no raw SQL, DSN or
write path here; task dispatch remains the existing ``TaskOrderCreate`` tool.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Callable

from .audit import record_step
from .identity import active_principal_payload
from .service import Process360Service

Executor = Callable[[dict[str, Any], str], str]

SCOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "查询范围；默认当期（本月至今），可指定观察截止日/期间/客户/负责人/产品。",
    "properties": {
        "asOf": {"type": "string", "description": "观察截止日 YYYY-MM-DD"},
        "periodStart": {"type": "string", "description": "期间开始日 YYYY-MM-DD"},
        "periodEnd": {"type": "string", "description": "期间结束日 YYYY-MM-DD"},
        "customerIds": {"type": "array", "items": {"type": "string"}},
        "ownerIds": {"type": "array", "items": {"type": "string"}},
        "productIds": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
        "includeCurrentSnapshot": {"type": "boolean", "default": False},
    },
    "additionalProperties": False,
}

PRINCIPAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Fuxi 宿主注入的可信身份和授权范围；服务端与查询筛选取交集，缺失时拒绝业务取数。",
    "properties": {
        "tenantId": {"type": "string", "description": "租户/公司 ID"},
        "userId": {"type": "string", "description": "当前用户 ID"},
        "orgIds": {"type": "array", "items": {"type": "string"}},
        "roles": {"type": "array", "items": {"type": "string"}},
        "customerIds": {"type": "array", "items": {"type": "string"}},
        "ownerIds": {"type": "array", "items": {"type": "string"}},
        "productIds": {"type": "array", "items": {"type": "string"}},
        "canDispatch": {"type": "boolean", "description": "是否允许点击发送任务令"},
        "source": {"type": "string", "description": "身份来源；默认 host"},
    },
    "required": ["tenantId", "userId"],
    "additionalProperties": False,
}


PROCESS360_ROUTE_SCHEMA: dict[str, Any] = {
    "name": "Process360Route",
    "description": (
        "Process360 S00 确定性路由：把问题映射到 P01-P18 SOP 与 SC01-SC05 场景，"
        "返回所需输入和澄清项。任何 Process360 分析前先调用。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "用户原话"},
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "planId": {"type": "string", "description": "修订已有计划时传入；服务端会记录修订理由"},
            "reviseReason": {"type": "string", "description": "计划修订原因；与原路由不同场景时必须提供"},
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}

PROCESS360_SEARCH_SCHEMA: dict[str, Any] = {
    "name": "Process360Search",
    "description": (
        "Process360 S01 双入口检索：只按指标和业务对象检索，返回命名命中、"
        "所属场景和建议的 S02 上下文。不要用它代替受控取数。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "指标/业务对象名称或编码"},
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

PROCESS360_CONTEXT_SCHEMA: dict[str, Any] = {
    "name": "Process360Context",
    "description": (
        "Process360 S02 场景上下文：返回流程、活动、业务对象、指标、角色、规则、"
        "异常、问题、风险、候选原因、方案、任务模板、Action、证据与缺口。只读本地 catalog。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "question": {"type": "string"},
        },
        "required": ["scenario"],
        "additionalProperties": False,
    },
}

PROCESS360_QUERY_SCHEMA: dict[str, Any] = {
    "name": "Process360Query",
    "description": (
        "Process360 S03 受控只读取数。按场景执行固定参数化 SQL，返回指标值、对象明细、"
        "证据和缺口。缺字段/历史快照/映射时返回 blocked 或 partial，绝不补 0。调用方不能传 SQL。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "queryId": {
                "type": "string",
                "description": "复用上一轮 Process360Query 返回的服务端结果引用；提供时不再重新查库",
            },
            "planId": {"type": "string", "description": "本轮 Process360Route 返回的计划；服务端校验场景一致"},
            "sample": {"type": "integer", "minimum": 0, "maximum": 50, "default": 5},
        },
        "required": ["scenario", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_ANALYZE_SCHEMA: dict[str, Any] = {
    "name": "Process360Analyze",
    "description": (
        "Process360 S04 分析：识别异常、量化已观察影响、给出候选原因与证据缺口。"
        "候选原因不得写成已确认根因；风险矩阵缺失时只输出运营分诊。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "queryId": {"type": "string", "description": "复用服务端查询结果；与 scope 同时提供时以该结果为口径"},
            "planId": {"type": "string", "description": "本轮 Process360Route 返回的计划；服务端校验场景一致"},
            "evidence": {
                "type": "array",
                "items": {"type": "object"},
                "description": "候选原因的证据；来源、对象/期间、规则、哈希与反证必须齐备才能 verified",
            },
            "forecastInputs": {
                "type": "object",
                "description": "P17 条件推算输入；缺实际值/目标/期间/假设时返回 blocked",
            },
        },
        "required": ["principal"],
        "anyOf": [{"required": ["question"]}, {"required": ["scenario"]}],
        "additionalProperties": False,
    },
}

PROCESS360_DRAFT_SCHEMA: dict[str, Any] = {
    "name": "Process360Draft",
    "description": (
        "Process360 S05 生成方案与任务令草稿。返回 tasks[]，可直接映射到 CanvasGenerate "
        "的 kind=actions items。草稿不含手机号；接收人由 Fuxi 宿主在用户点击时提供。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "runId": {"type": "string", "description": "服务端分析运行 ID；有值时以其冻结分析为准"},
            "queryId": {"type": "string", "description": "复用服务端查询结果引用"},
            "principal": PRINCIPAL_SCHEMA,
            "ownerRef": {"type": "string", "description": "唯一牵头人 ID（可空）"},
            "ownerName": {"type": "string"},
            "dueAt": {"type": "string", "description": "ISO 8601；不填不虚构期限"},
            "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "solutions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["principal"],
        "anyOf": [{"required": ["question"]}, {"required": ["scenario"]}],
        "additionalProperties": False,
    },
}

PROCESS360_VERIFY_SCHEMA: dict[str, Any] = {
    "name": "Process360Verify",
    "description": (
        "Process360 S07 复验：返回交付验收与效果验收的独立结论。缺冻结基准或批准 RF 目标时"
        "返回 blocked，不能宣称整改达标或关闭问题。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "runId": {"type": "string", "description": "Process360Analyze 返回的服务端冻结运行"},
            "queryId": {"type": "string", "description": "复用服务端查询结果引用"},
            "approvalRef": {"type": "string", "description": "业务批准记录编号"},
            "approvedTarget": {"type": "number", "description": "批准目标比例"},
            "approvedDirection": {"type": "string", "enum": [">=", "<="]},
            "approvedMinimumDenominator": {"type": "integer", "minimum": 1},
            "excludedObjectKeys": {"type": "array", "items": {"type": "string"}},
            "exclusionEvidence": {"type": "object", "description": "逐对象取消/移出批准证据"},
            "deliveryEvidence": {"type": "object", "description": "交付验收凭据"},
        },
        "required": ["scenario", "principal", "runId"],
        "additionalProperties": False,
    },
}

PROCESS360_PLAN_SCHEMA: dict[str, Any] = {
    "name": "Process360Plan",
    "description": (
        "S00 多目标 DAG：把复合问题拆成相互依赖的只读子目标，保存计划版本、恢复点、"
        "共享调用/耗时/行数预算。总览不自动下发任务，也不调用业务写接口。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "budget": {
                "type": "object",
                "properties": {
                    "calls": {"type": "integer", "minimum": 1, "maximum": 50},
                    "elapsedMs": {"type": "integer", "minimum": 500, "maximum": 600000},
                    "rows": {"type": "integer", "minimum": 1, "maximum": 100000},
                },
            },
        },
        "required": ["question", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_EXPLORE_SCHEMA: dict[str, Any] = {
    "name": "Process360Explore",
    "description": (
        "S08 受控自主探索：仅执行计划白名单内的只读 Process360 工具，按计划共享预算、"
        "请求哈希去重和 path_gap 返回原步骤。不能下发任务或执行 SQL。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "planId": {"type": "string"},
            "stepId": {"type": "string"},
            "tool": {
                "type": "string",
                "enum": [
                    "Process360Search", "Process360Context", "Process360Query", "Process360Analyze",
                    "Process360Compare", "Process360Structure", "Process360ProcessFlow",
                    "Process360Progress", "Process360Forecast",
                ],
            },
            "parameters": {"type": "object"},
            "principal": PRINCIPAL_SCHEMA,
        },
        "required": ["planId", "stepId", "tool", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_COMPARE_SCHEMA: dict[str, Any] = {
    "name": "Process360Compare",
    "description": "P04 多期对比：当前期与上一同长度期间分别取数，零基期不计算增长率，阻断指标不补零。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "periods": {"type": "integer", "minimum": 2, "maximum": 12, "default": 2},
        },
        "required": ["scenario", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_STRUCTURE_SCHEMA: dict[str, Any] = {
    "name": "Process360Structure",
    "description": "P05 结构排名：从本次受控明细按已映射维度汇总、排名、占比；未知维度单列，统计贡献不当作原因。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "scope": SCOPE_SCHEMA,
            "principal": PRINCIPAL_SCHEMA,
            "queryId": {"type": "string", "description": "复用服务端查询结果引用"},
            "dimension": {"type": "string"},
            "valueField": {"type": "string"},
            "topN": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "required": ["scenario", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_PROCESS_FLOW_SCHEMA: dict[str, Any] = {
    "name": "Process360ProcessFlow",
    "description": "P07 流程堵点：按同一对象键与批次计算节点转化、在办量和停留；缺阶段轨迹时阻断，不用两节点总数相除。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "stages": {"type": "array", "items": {"type": "object"}},
            "objectKey": {"type": "string", "default": "objectId"},
            "batchKey": {"type": "string", "default": "batchId"},
            "principal": PRINCIPAL_SCHEMA,
        },
        "required": ["scenario", "principal"],
        "additionalProperties": False,
    },
}

PROCESS360_PROGRESS_SCHEMA: dict[str, Any] = {
    "name": "Process360Progress",
    "description": "P14 任务进度：按权限读取本服务可恢复的执行记录与 Fuxi 推送回执；口头完成不等于业务回执。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "draftId": {"type": "string"},
            "principal": PRINCIPAL_SCHEMA,
        },
        "required": ["principal"],
        "additionalProperties": False,
    },
}

PROCESS360_FORECAST_SCHEMA: dict[str, Any] = {
    "name": "Process360Forecast",
    "description": "P17 条件预测：只有提供实际值、目标、期间进度与显式假设时才做规则推算；不伪装为正式模型或承诺。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "actualToDate": {"type": "number"},
            "target": {"type": "number"},
            "elapsedDays": {"type": "integer", "minimum": 1},
            "totalDays": {"type": "integer", "minimum": 1},
            "assumption": {"type": "string"},
            "principal": PRINCIPAL_SCHEMA,
        },
        "required": ["principal", "assumption"],
        "additionalProperties": False,
    },
}

PROCESS360_SOLUTIONS_SCHEMA: dict[str, Any] = {
    "name": "Process360Solutions",
    "description": "S05 方案结构和约束校验：唯一牵头人、协同、期限、验收、审批前置；无批准效果/成本/周期依据时不生成综合评分或推荐。",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario": {"type": "string", "enum": ["SC01", "SC02", "SC03", "SC04", "SC05"]},
            "tasks": {"type": "array", "items": {"type": "object"}},
            "options": {"type": "array", "items": {"type": "object"}},
            "dueAt": {"type": "string"},
            "principal": PRINCIPAL_SCHEMA,
        },
        "required": ["principal"],
        "additionalProperties": False,
    },
}


def _without_principal(spec: dict[str, Any]) -> dict[str, Any]:
    """Public schemas never expose the identity field.

    The principal is injected by the server for each tool call.  Removing it
    here (rather than trusting every caller) also means the strict
    ``additionalProperties: False`` validator rejects a model that tries to
    supply one.
    """
    schema = dict(spec)
    input_schema = dict(schema.get("input_schema") or {})
    properties = dict(input_schema.get("properties") or {})
    properties.pop("principal", None)
    input_schema["properties"] = properties
    if "required" in input_schema:
        required = [item for item in input_schema["required"] if item != "principal"]
        if required:
            input_schema["required"] = required
        else:
            input_schema.pop("required")
    schema["input_schema"] = input_schema
    return schema


def _with_plan_refs(spec: dict[str, Any]) -> dict[str, Any]:
    """Expose plan/step references; the public MCP runtime makes them mandatory."""
    schema = deepcopy(spec)
    properties = schema.setdefault("input_schema", {}).setdefault("properties", {})
    properties.setdefault(
        "planId",
        {"type": "string", "description": "Process360Route/Plan 返回的服务端执行计划"},
    )
    properties.setdefault(
        "stepId",
        {"type": "string", "description": "当前计划 steps[] 中的步骤 ID"},
    )
    return schema


SPECS = tuple(_without_principal(spec) for spec in (
    PROCESS360_ROUTE_SCHEMA,
    PROCESS360_SEARCH_SCHEMA,
    PROCESS360_CONTEXT_SCHEMA,
    _with_plan_refs(PROCESS360_QUERY_SCHEMA),
    _with_plan_refs(PROCESS360_ANALYZE_SCHEMA),
    _with_plan_refs(PROCESS360_DRAFT_SCHEMA),
    _with_plan_refs(PROCESS360_VERIFY_SCHEMA),
    PROCESS360_PLAN_SCHEMA,
    PROCESS360_EXPLORE_SCHEMA,
    _with_plan_refs(PROCESS360_COMPARE_SCHEMA),
    _with_plan_refs(PROCESS360_STRUCTURE_SCHEMA),
    _with_plan_refs(PROCESS360_PROCESS_FLOW_SCHEMA),
    _with_plan_refs(PROCESS360_PROGRESS_SCHEMA),
    _with_plan_refs(PROCESS360_FORECAST_SCHEMA),
    _with_plan_refs(PROCESS360_SOLUTIONS_SCHEMA),
))


def _service(cwd: str) -> Process360Service:
    return Process360Service(cwd=cwd)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _principal(params: dict[str, Any]) -> dict[str, Any] | None:
    """Trusted identity for this call.

    The MCP runtime injects the server-resolved principal through a context
    variable.  ``params["principal"]`` only exists for direct in-process
    callers (tests, the web dispatch route) and is never model-visible.
    """
    injected = active_principal_payload()
    if injected:
        return dict(injected)
    return params.get("principal")


def _route(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).route(
            str(params.get("question") or ""),
            scenario=params.get("scenario"),
            plan_id=str(params.get("planId") or ""),
            revise_reason=str(params.get("reviseReason") or ""),
            principal=_principal(params),
        )
    )


def _search(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).search(
            str(params.get("query") or ""),
            scenario=params.get("scenario"),
            limit=int(params.get("limit") or 20),
        )
    )


def _context(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).context(str(params.get("scenario") or ""), question=params.get("question"))
    )


def _query(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).query(
            str(params.get("scenario") or ""),
            scope=params.get("scope"),
            principal=_principal(params),
            query_id=str(params.get("queryId") or ""),
            sample=int(params.get("sample") if params.get("sample") is not None else 5),
            plan_id=str(params.get("planId") or ""),
        )
    )


def _analyze(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).analyze(
            question=str(params.get("question") or ""),
            scenario=params.get("scenario"),
            scope=params.get("scope"),
            principal=_principal(params),
            query_id=str(params.get("queryId") or ""),
            plan_id=str(params.get("planId") or ""),
            evidence=params.get("evidence"),
            forecast_inputs=params.get("forecastInputs"),
        )
    )


def _draft(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).draft(
            question=str(params.get("question") or ""),
            scenario=params.get("scenario"),
            scope=params.get("scope"),
            run_id=str(params.get("runId") or ""),
            query_id=str(params.get("queryId") or ""),
            principal=_principal(params),
            owner_ref=str(params.get("ownerRef") or ""),
            owner_name=str(params.get("ownerName") or ""),
            due_at=str(params.get("dueAt") or ""),
            severity=params.get("severity"),
            solutions=params.get("solutions"),
        )
    )


def _verify(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).verify(
            scenario=str(params.get("scenario") or ""),
            scope=params.get("scope"),
            run_id=str(params.get("runId") or ""),
            principal=_principal(params),
            query_id=str(params.get("queryId") or ""),
            approval_ref=str(params.get("approvalRef") or ""),
            approved_target=params.get("approvedTarget"),
            approved_direction=str(params.get("approvedDirection") or ""),
            approved_minimum_denominator=params.get("approvedMinimumDenominator"),
            excluded_object_keys=params.get("excludedObjectKeys"),
            exclusion_evidence=params.get("exclusionEvidence"),
            delivery_evidence=params.get("deliveryEvidence"),
        )
    )


def _plan(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).plan(
            question=str(params.get("question") or ""),
            scenario=params.get("scenario"),
            scope=params.get("scope"),
            principal=_principal(params),
            budget=params.get("budget"),
        )
    )


def _explore(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).explore(
            plan_id=str(params.get("planId") or ""),
            step_id=str(params.get("stepId") or ""),
            tool=str(params.get("tool") or ""),
            parameters=params.get("parameters"),
            principal=_principal(params),
        )
    )


def _compare(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).compare_periods(
            str(params.get("scenario") or ""),
            scope=params.get("scope"),
            principal=_principal(params),
            periods=int(params.get("periods") or 2),
        )
    )


def _structure(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).structure(
            str(params.get("scenario") or ""),
            scope=params.get("scope"),
            principal=_principal(params),
            dimension=str(params.get("dimension") or ""),
            value_field=str(params.get("valueField") or ""),
            top_n=int(params.get("topN") or 10),
            query_id=str(params.get("queryId") or ""),
        )
    )


def _process_flow(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).process_flow(
            str(params.get("scenario") or ""),
            stages=params.get("stages"),
            object_key=str(params.get("objectKey") or "objectId"),
            batch_key=str(params.get("batchKey") or "batchId"),
            principal=_principal(params),
        )
    )


def _progress(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).progress(
            scenario=params.get("scenario"),
            draft_id=str(params.get("draftId") or ""),
            principal=_principal(params),
        )
    )


def _forecast(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).forecast(
            actual_to_date=params.get("actualToDate"),
            target=params.get("target"),
            elapsed_days=params.get("elapsedDays"),
            total_days=params.get("totalDays"),
            assumption=str(params.get("assumption") or ""),
            scenario=params.get("scenario"),
            principal=_principal(params),
        )
    )


def _solutions(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).review_solutions(
            tasks=params.get("tasks"),
            options=params.get("options"),
            due_at=str(params.get("dueAt") or ""),
            scenario=params.get("scenario"),
            principal=_principal(params),
        )
    )


EXECUTORS: dict[str, Executor] = {
    "Process360Route": _route,
    "Process360Search": _search,
    "Process360Context": _context,
    "Process360Query": _query,
    "Process360Analyze": _analyze,
    "Process360Draft": _draft,
    "Process360Verify": _verify,
    "Process360Plan": _plan,
    "Process360Explore": _explore,
    "Process360Compare": _compare,
    "Process360Structure": _structure,
    "Process360ProcessFlow": _process_flow,
    "Process360Progress": _progress,
    "Process360Forecast": _forecast,
    "Process360Solutions": _solutions,
}


def _validated_executor(spec: dict[str, Any], executor: Executor) -> Executor:
    """Enforce the public contract even when an MCP host skips JSON-schema validation."""
    schema = spec["input_schema"]
    tool_name = str(spec.get("name") or "")

    def validate(value: Any, rule: dict[str, Any]) -> None:
        kind = rule.get("type")
        valid = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": type(value) is int,
            "boolean": type(value) is bool,
        }.get(kind, True)
        if not valid:
            raise ValueError("Process360 argument has an invalid type")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError("Process360 argument is outside allowed values")
        if kind == "object":
            properties = rule.get("properties", {})
            if rule.get("additionalProperties") is False and set(value) - set(properties):
                raise ValueError("Process360 contains unsupported arguments")
            if any(key not in value for key in rule.get("required", [])):
                raise ValueError("Process360 required argument is missing")
            if rule.get("anyOf") and not any(
                all(key in value for key in branch.get("required", [])) for branch in rule["anyOf"]
            ):
                raise ValueError("Process360 requires question or scenario")
            for key in value.keys() & properties.keys():
                validate(value[key], properties[key])
        elif kind == "array":
            for item in value:
                validate(item, rule.get("items", {}))
        elif kind == "integer" and not rule.get("minimum", value) <= value <= rule.get(
            "maximum", value
        ):
            raise ValueError("Process360 argument is outside allowed bounds")

    def run(params: dict[str, Any], cwd: str) -> str:
        import time as _time

        validate(params, schema)
        started = _time.monotonic()
        result = executor(params, cwd)
        record_step(
            tool_name,
            params,
            result,
            duration_ms=int((_time.monotonic() - started) * 1000),
        )
        return result

    return run


EXECUTORS = {spec["name"]: _validated_executor(spec, EXECUTORS[spec["name"]]) for spec in SPECS}
