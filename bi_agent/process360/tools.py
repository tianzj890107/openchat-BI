"""MCP-facing Process360 tool catalog.

The tools expose the deterministic engine only.  There is no raw SQL, DSN or
write path here; task dispatch remains the existing ``TaskOrderCreate`` tool.
"""

from __future__ import annotations

import json
from typing import Any, Callable

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
        },
        "required": ["scenario"],
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
        },
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
            "ownerRef": {"type": "string", "description": "唯一牵头人 ID（可空）"},
            "ownerName": {"type": "string"},
            "dueAt": {"type": "string", "description": "ISO 8601；不填不虚构期限"},
            "severity": {"type": "string", "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "solutions": {"type": "array", "items": {"type": "string"}},
        },
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
            "baseline": {"type": "object", "description": "原问题集合的冻结基准"},
            "deliveryEvidence": {"type": "object", "description": "交付验收凭据"},
        },
        "required": ["scenario"],
        "additionalProperties": False,
    },
}

SPECS = (
    PROCESS360_ROUTE_SCHEMA,
    PROCESS360_SEARCH_SCHEMA,
    PROCESS360_CONTEXT_SCHEMA,
    PROCESS360_QUERY_SCHEMA,
    PROCESS360_ANALYZE_SCHEMA,
    PROCESS360_DRAFT_SCHEMA,
    PROCESS360_VERIFY_SCHEMA,
)


def _service(cwd: str) -> Process360Service:
    return Process360Service(cwd=cwd)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _route(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).route(str(params.get("question") or ""), scenario=params.get("scenario"))
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
    return _json(_service(cwd).query(str(params.get("scenario") or ""), scope=params.get("scope")))


def _analyze(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).analyze(
            question=str(params.get("question") or ""),
            scenario=params.get("scenario"),
            scope=params.get("scope"),
        )
    )


def _draft(params: dict[str, Any], cwd: str) -> str:
    return _json(
        _service(cwd).draft(
            question=str(params.get("question") or ""),
            scenario=params.get("scenario"),
            scope=params.get("scope"),
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
            baseline=params.get("baseline"),
            delivery_evidence=params.get("deliveryEvidence"),
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
}


def _validated_executor(spec: dict[str, Any], executor: Executor) -> Executor:
    """Enforce the public contract even when an MCP host skips JSON-schema validation."""
    schema = spec["input_schema"]

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
        validate(params, schema)
        return executor(params, cwd)

    return run


EXECUTORS = {spec["name"]: _validated_executor(spec, EXECUTORS[spec["name"]]) for spec in SPECS}
