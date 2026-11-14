"""Opportunity V2: ontology rules first, database evidence, AP only as fallback.

This module is deliberately independent from the shared ``opportunity`` stage
analysis.  The card is a deterministic, read-only execution of the reviewed V2
ontology:

1. load a versioned, hash-audited runtime config;
2. collect fixed, parameterised facts from the customer PostgreSQL snapshot;
3. evaluate indicator/risk rules in program code (never in SQL supplied by a
   model and never by asking a model to choose tables);
4. query only the details needed by risks that actually triggered;
5. project the rule-backed risks, candidate causes and advice templates into a
   ``cockpit-cards-v1`` payload.

The module never writes to the customer database.  Empty values stay empty;
a real zero and a rule that did not trigger are valid results.  The card is
published separately from the shared opportunity stage so that refreshing it
cannot replace the coverage-note card.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import contextvars
from copy import deepcopy
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import time
import uuid

CONFIG_PATH = Path(__file__).parent / "assets/opportunity-v3/config.json"
SLOT_ID = "opportunity-risk"
RULES_VERSION = "opportunity-v3-rules-8"

_LEVEL_RANK = {"极高": 0, "高": 1, "中": 2, "低": 3}
_CAUSE_STAGE = {
    "RC01": "opportunity", "RC02": "bid", "RC03": "opportunity",
    "RC04": "opportunity", "RC05": "opportunity", "RC06": "opportunity",
    "RC07": "opportunity", "RC08": "opportunity", "RC09": "opportunity",
}
# Governance actions repair the measurement source itself; they must not take
# the place of business remediation in the重点建议 slot.
_GOVERNANCE_ADVICE = {"AC05"}
_AP_SUPPLEMENT_CODES = {
    "B01.amount": "YWLN_M0002",
    "B01.energy": "YWLN_M0007",
    "B02.amount": "YWLN_M0023",
    "B02.energy": "YWLN_M0022",
}
_RISK_FACT_CODES = {
    "RK01": ("B01-AMOUNT", "B01-ENERGY", "B02-AMOUNT", "B02-ENERGY",
             "R01-AMOUNT", "R01-ENERGY", "R01-RATE-AMOUNT", "R01-RATE-ENERGY"),
    "RK02": ("R03-LAG", "R03-LAG-ENERGY", "R02-AMOUNT", "R02-ENERGY",
             "R02-CONFIRMED-AMOUNT", "R02-CONFIRMED-ENERGY", "B02-AMOUNT", "B02-ENERGY"),
    "RK03": ("R04-COUNT", "R04-AMOUNT", "R04-ENERGY", "R01-AMOUNT", "R01-ENERGY"),
    "RK04": ("R05-AMOUNT", "R05-ENERGY", "B01-AMOUNT", "B01-ENERGY",
             "B02-AMOUNT", "B02-ENERGY", "R03-LAG", "R03-LAG-ENERGY"),
    "RK05": ("R06-AMOUNT", "R06-ENERGY", "B01-AMOUNT", "B01-ENERGY",
             "B02-AMOUNT", "B02-ENERGY", "R03-LAG", "R03-LAG-ENERGY"),
    "RK06": ("R08",),
    "RK07": ("R09",),
    "RK08": ("R10", "BID-AMBIGUOUS"),
    "RK09": ("R11", "S03", "S03-P1", "S03-P2"),
    "RK10": ("P0-01", "P0-02", "P2-01"),
}
_CONFIG_CACHE: dict[str, tuple[int, dict]] = {}


class OpportunityV2Unavailable(RuntimeError):
    """The card cannot be produced without inventing evidence."""


class OpportunityV2ModelUnavailable(OpportunityV2Unavailable):
    """The model step did not produce a validated business analysis.

    The card is not published: no previous card and no ontology template
    replaces the model's analysis.  The failure is shown to the user.
    """

    def __init__(self, message, *, status="failed", error="", missing=None):
        super().__init__(message)
        self.phase = "model"
        self.code = "MODEL_ANALYSIS_INCOMPLETE"
        self.model_status = status
        self.model_error = error
        self.missing_risk_codes = list(missing or [])
        self.diagnostic_message = (
            f"modelStatus={status}; error={error or 'none'}; "
            f"missingRiskCodes={','.join(self.missing_risk_codes) or 'none'}"
        )


class ModelJSONOutputError(RuntimeError):
    """The model returned text, but it could not be accepted as JSON."""

    def __init__(self, message, *, raw_text="", repair_text="", stop_reason="", attempts=1):
        super().__init__(message)
        self.raw_text = str(raw_text or "")
        self.repair_text = str(repair_text or "")
        self.stop_reason = str(stop_reason or "")
        self.attempts = int(attempts or 1)


class ModelJSONResult(dict):
    """Parsed model output carrying non-payload call metadata."""

    def __init__(self, value, *, model_calls=1):
        super().__init__(value)
        self.model_calls = int(model_calls or 1)


def _text(value):
    return str(value).strip() if value is not None else ""


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value, digits=2):
    number = _number(value)
    return None if number is None else round(number, digits)


def _sum(values):
    found = [_number(value) for value in values]
    found = [value for value in found if value is not None]
    return round(sum(found), 6) if found else None


def _div(part, total):
    part, total = _number(part), _number(total)
    return part / total if part is not None and total not in (None, 0) else None


def _day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _iso(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else (value or None)


def _slug(value):
    return re.sub(r"[^a-z0-9_]+", "_", _text(value).lower()).strip("_") or "value"


def _customer_tier_config(config=None):
    return ((config or {}).get("overrides") or {}).get("customerTier") or {}


def _strategic_scope(config=None):
    """Whether the ontology supplies an executable strategic-customer rule.

    DR04 in the ontology is an executable customer-level rule.  The absence of
    a separate customer-name sheet is recorded as a limitation, not a reason to
    disable the rule; inventing a list here would be a mapping of our own.
    """
    tier = _customer_tier_config(config)
    meta = (tier.get("tierMeta") or {}).get("strategic") or {}
    levels = [_text(value) for value in tier.get("strategic") or [] if _text(value)]
    rule = _text(meta.get("rule")) or _text(tier.get("rule"))
    if levels and rule:
        return True, ""
    reason = _text(tier.get("statusReason")) or "本体未提供可执行的战略客户派生规则"
    return False, reason


def _customer_tier(level, config=None):
    level = _text(level)
    mapping = _customer_tier_config(config)
    strategic_ok = _strategic_scope(config)[0]
    for tier in ("strategic", "priority", "general"):
        if level in {_text(value) for value in mapping.get(tier) or []}:
            return "unknown" if tier == "strategic" and not strategic_ok else tier
    # V3 DR06 is a catch-all ("其余等级").  An empty level stays unknown per
    # BR-Q04 ("等级未知不当一般客户").
    if level and mapping.get("generalCatchAll"):
        return "general"
    return "unknown"


def _product_name(value, config=None):
    names = ((config or {}).get("overrides") or {}).get("products") or {}
    return names.get(_text(value)) or (_text(value) or "未分类")


def _stage_name(value, config=None):
    names = ((config or {}).get("overrides") or {}).get("stage") or {}
    return names.get(_text(value)) or (_text(value) or "未分类")


_THRESHOLD_KEYS = ("gapRateHigh", "gapRateMedium", "signLagExtremePoints",
                   "signLagHighPoints", "focusTrackingRatio", "productPendingRatio",
                   "otherPendingRatio", "productRiskAmountHigh",
                   "productRiskAmountMedium", "impactAmountHigh")


def _thresholds(config):
    value = ((config or {}).get("overrides") or {}).get("thresholds") or {}
    missing = [key for key in _THRESHOLD_KEYS if _number(value.get(key)) is None]
    quarters = value.get("quarterWindows") or {}
    if _number(quarters.get("3")) is None or _number(quarters.get("4")) is None:
        missing.append("quarterWindows")
    if missing:
        raise OpportunityV2Unavailable("本体业务规则未定义阈值：" + "、".join(missing))
    return dict(
        gapRateHigh=_number(value["gapRateHigh"]),
        gapRateMedium=_number(value["gapRateMedium"]),
        signLagExtremePoints=_number(value["signLagExtremePoints"]),
        signLagHighPoints=_number(value["signLagHighPoints"]),
        quarterWindows={"3": _number(quarters["3"]), "4": _number(quarters["4"])},
        focusTrackingRatio=_number(value["focusTrackingRatio"]),
        productPendingRatio=_number(value["productPendingRatio"]),
        otherPendingRatio=_number(value["otherPendingRatio"]),
        productRiskAmountHigh=_number(value["productRiskAmountHigh"]),
        productRiskAmountMedium=_number(value["productRiskAmountMedium"]),
        impactAmountHigh=_number(value["impactAmountHigh"]),
    )


def load_config():
    """Load and validate the reviewed runtime config; never read the workbook."""
    stamp = CONFIG_PATH.stat().st_mtime_ns
    cached = _CONFIG_CACHE.get(str(CONFIG_PATH))
    if cached and cached[0] == stamp:
        return cached[1]
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("version") != RULES_VERSION:
        raise OpportunityV2Unavailable("商机 V3 运行配置版本不匹配")
    source = config.get("source") or {}
    # The authoring workbook is not shipped to customers.  When it is present
    # in a development checkout, verify it; the config hash always protects the
    # deployed artifact through the release version.
    source_path = Path(__file__).parents[2] / str(source.get("path") or "")
    if source.get("path") and source_path.exists():
        actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source.get("sha256") and actual != source["sha256"]:
            raise OpportunityV2Unavailable("商机 V3 本体源文件与运行配置哈希不一致")
    risks = set(config.get("risks") or {})
    causes = set(config.get("causes") or {})
    advice = set(config.get("advice") or {})
    for risk, link in (config.get("links") or {}).items():
        if risk not in risks:
            raise OpportunityV2Unavailable(f"V3 链路引用未知风险：{risk}")
        if not set(link.get("causes") or []) <= causes:
            raise OpportunityV2Unavailable(f"V3 链路引用未知根因：{risk}")
        if not set(link.get("advice") or []) <= advice:
            raise OpportunityV2Unavailable(f"V3 链路引用未知建议：{risk}")
    if "RK07" in (config.get("links") or {}):
        rk07_causes = config["links"]["RK07"].get("causes") or []
        if "RC01" in rk07_causes or rk07_causes != ["RC09"]:
            raise OpportunityV2Unavailable("RK07 必须只关联 RC09，不能保留 RC01 的矛盾关联")
    _CONFIG_CACHE[str(CONFIG_PATH)] = (stamp, config)
    return config


def config_version():
    return load_config().get("version", "")


def config_digest():
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()


def _database():
    from ..process360.db import DatabaseConfig, PostgresDatabase
    config = DatabaseConfig.from_env()
    if not config.ready()[0]:
        host = os.environ.get("WORKBENCH_PG_HOST", "").strip()
        database = os.environ.get("WORKBENCH_PG_DATABASE", "").strip()
        user = os.environ.get("WORKBENCH_PG_USER", "").strip()
        if host and database and user:
            def integer(name, default):
                try:
                    return int(os.environ.get(name, str(default)))
                except ValueError:
                    return default
            config = DatabaseConfig(
                host=host,
                port=integer("WORKBENCH_PG_PORT", 5432),
                database=database,
                user=user,
                password=os.environ.get("WORKBENCH_PG_PASSWORD", ""),
                schema=(os.environ.get("PROCESS360_PG_SCHEMA")
                        or os.environ.get("WORKBENCH_PG_SCHEMA") or "ded_public").strip(),
                connect_timeout=max(1, min(integer("WORKBENCH_PG_CONNECT_TIMEOUT", 5), 30)),
                statement_timeout_ms=max(1000, min(integer("WORKBENCH_PG_STATEMENT_TIMEOUT_MS", 90000), 120000)),
            )
    if not config.ready()[0]:
        raise OpportunityV2Unavailable("未配置商机 V3 只读数据库：" + config.ready()[1])
    return PostgresDatabase(config, max_rows=20000)


def _table(config, entity):
    table = _text((config.get("logicalEntities", {}).get(entity) or {}).get("table"))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", table):
        raise OpportunityV2Unavailable(f"V3 逻辑实体缺少合法物理表：{entity}")
    schema, name = table.split(".", 1)
    return f'"{schema}"."{name}"'


def _physical_table_name(value):
    table = _text(value)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", table):
        raise OpportunityV2Unavailable("V3 近期活动来源缺少合法物理表")
    schema, name = table.split(".", 1)
    return f'"{schema}"."{name}"'


def _columns(config, entity):
    result = {}
    for name, item in ((config.get("fields") or {}).get(entity) or {}).items():
        column = _text(item.get("column"))
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
            result[name] = column
    return result


def _measurement_date(period, requested=None):
    if requested:
        value = _day(requested)
        if value:
            return value
    year = int(period)
    today = date.today()
    if year < today.year:
        return date(year, 12, 31)
    if year > today.year:
        return date(year, 1, 1)
    return today


def _safe_year(period):
    value = _text(period)
    if not re.fullmatch(r"\d{4}", value):
        raise OpportunityV2Unavailable("商机 V3 只接受四位年度期间")
    return int(value)


def _report_progress(progress, phase, **detail):
    """Progress reporting is observational and must never break evidence work."""
    if progress is None:
        return
    try:
        progress(phase, **detail)
    except Exception:  # noqa: BLE001 - a UI callback cannot fail the analysis
        pass


def _query_timeout_ms():
    """One statement is capped at 30 seconds unless explicitly lowered."""
    try:
        configured = int(os.environ.get("COCKPIT_OPPORTUNITY_V2_QUERY_TIMEOUT_MS", "30000"))
    except ValueError:
        configured = 30000
    return max(1000, min(configured, 30000))


def _fetch_budget_seconds():
    try:
        configured = int(os.environ.get("COCKPIT_OPPORTUNITY_V2_FETCH_BUDGET_SECONDS", "60"))
    except ValueError:
        configured = 60
    return max(5, min(configured, 300))


@contextmanager
def _reader_group(database, workers=3):
    """Yield ``(readers, parallel)`` for one shared PostgreSQL snapshot."""
    if hasattr(database, "snapshot_group"):
        with database.snapshot_group(workers) as readers:
            yield list(readers), True
        return
    # Older/fake adapters only expose a single reader.  Keeping that path
    # sequential preserves snapshot semantics and test doubles.
    if hasattr(database, "snapshot"):
        with database.snapshot() as reader:  # type: ignore[union-attr]
            yield [reader], False
        return
    yield [database], False


def _query_failure(exc, label, duration):
    sqlstate = _text(getattr(exc, "sqlstate", "") or getattr(exc, "pgcode", "")
                     or getattr(exc, "upstream_code", ""))
    original = _text(getattr(exc, "original_message", "") or str(exc))
    return dict(
        phase="database_query", query=label or "optional",
        code=type(exc).__name__, upstreamCode=sqlstate,
        message=original[:1200], durationSeconds=round(duration, 3),
    )


# Which ontology metrics each query's rows are computed into; each risk or
# cause lists only the queries behind the metrics of its own evidence.
_QUERY_METRICS = {
    "销售目标": ["B01", "R01", "R05", "R06", "R08"],
    "产品类型": ["R05", "R06"],
    "商机预测": ["B02", "R01", "R02", "R03", "R04", "R05", "R06", "R08", "C01", "C06", "C07", "C08",
                 "C09", "P0-01", "P0-02", "P2-01", "P2-02"],
    "商机聚合": ["B02", "R01", "R02", "R03", "R04", "R05", "R06", "R08"],
    # Read for display or as a legacy fallback only; no rule is computed from them.
    "全部商机": [],
    "客户": ["R09"],
    "投标": [],
    "项目进展": [],
    "订单关联": [],
    "产品团队": [],
    "产品部销售缺口": ["C03", "C04", "C05"],
}

_QUERY_AGGREGATION_NOTES = {
    "销售目标": "B01：同一商机（商机为空时按目标 ID）同一年度只取最新一条目标后汇总；amount_yuan / 1e8 = 目标金额（亿元），电量按配置单位换算为 GWh。",
    "产品类型": "产品类型枚举映射：1=电芯，2=PACK，空或其他=其他；只用于维度归类，不参与金额汇总。",
    "商机预测": "BR-Q01：所选年度内同商机同月取最新一版月度预测后按商机汇总；金额只用 new_forecast_amt_rmb，不混入已历月份实绩；电量 = new_forecast_amt_rmb ÷ new_whprice（元/Wh）÷ 1e9；不限定审核或业务状态。",
    "全部商机": "每个商机 ID 取最新一行，创建时间不晚于观察日结束（创建时间为空也保留）；不限定审核或业务状态；用于阶段周期，不直接求和。",
    "客户": "每个客户 ID 取最新一行；客户等级 1 为战略客户（本体 DR04）；本体启用 BR-Q04 时只保留储能客户名单内的客户（商机负责人→团队→团队人员→客户负责人）；opportunity_count 为该客户全部关联商机数（R09 不按年份或状态筛选）。",
    "投标": "投标项目按输入时间不晚于观察时点过滤；同名多版本不擅自取最新，按样本记录标记。",
    "项目进展": "按商机取进展记录，用于原因文本证据；不做数值汇总。",
    "订单关联": "BR-Q02：按订单明细关联商机，去重订单数 ≥ 1 为已签单；不限定审批、取消状态或订单日期。",
    "产品团队": "团队成员关系按商机归属去重；同一人属于多团队时不强行合并。",
    "商机聚合": "明细行被截断时用于恢复全量聚合；仅参与规则计算，不在明细表展示。",
}


def _query_sample_limit() -> int:
    try:
        value = int(os.environ.get("COCKPIT_QUERY_SAMPLE_ROWS", "100"))
    except ValueError:
        value = 100
    return max(0, min(value, 500))


def _json_safe(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, datetime_time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _query_result_meta(rows: list[dict]) -> dict:
    normalized = [_json_safe(dict(row)) for row in rows]
    limit = _query_sample_limit()
    columns: list[str] = []
    for row in normalized[:50]:
        for key in row:
            if key not in columns:
                columns.append(key)
    sample = normalized[:limit]
    body = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return dict(
        resultHash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        columns=columns,
        sampleRows=sample,
        sampleRowCount=len(sample),
        sampleTruncated=len(normalized) > len(sample),
        sampleLimit=limit,
    )

def _ontology_metric_sql(config, code, year, measured, schema="ded_public"):
    """The ontology's registered SQL for ``code``, bound to one year.

    The workbook SQL has no bind parameters: the period lives in its
    ``parameters`` CTE and the observation time is ``CURRENT_TIMESTAMP``.
    Both are replaced so a run is reproducible for its measurement date.
    """
    metric = next((item for item in (config.get("metrics") or {}).values()
                   if isinstance(item, dict) and item.get("code") == code), None) \
        if isinstance(config.get("metrics"), dict) else next(
            (item for item in config.get("metrics") or [] if item.get("code") == code), None)
    sql = _text((metric or {}).get("sql"))
    if not sql:
        return ""
    # The period may be written DATE '…' or CAST('…' AS DATE) depending on the
    # workbook version; each bound must appear exactly once.
    bounds = {"start_date": f"{int(year)}-01-01", "end_exclusive": f"{int(year) + 1}-01-01"}
    for name, value in bounds.items():
        pattern = (r"(?:DATE\s+'\d{4}-\d{2}-\d{2}'|CAST\(\s*'\d{4}-\d{2}-\d{2}'\s+AS\s+DATE\s*\))"
                   r"\s+AS\s+" + name + r"\b")
        sql, count = re.subn(pattern, f"DATE '{value}' AS {name}", sql, flags=re.I)
        if count != 1:
            return ""
    observed = f"TIMESTAMP '{measured.isoformat()} 23:59:59'"
    sql = re.sub(r"CAST\(\s*CURRENT_TIMESTAMP\s+AS\s+TIMESTAMP\s*\)|CURRENT_TIMESTAMP::timestamp",
                 observed, sql, flags=re.I)
    if re.search(r"\bCURRENT_TIMESTAMP\b", sql, flags=re.I):
        return ""
    if schema and schema != "ded_public" and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        sql = sql.replace("ded_public.", f"{schema}.")
    # The read-only guard requires the statement to start with SELECT/WITH,
    # and the workbook SQL opens with "--" comment lines.  Comments carry no
    # logic, so they are removed (outside string literals) before execution.
    sql = _strip_sql_comments(sql).strip().rstrip(";").rstrip()
    # The SQL runs with an (empty) parameter tuple, so psycopg reads every "%"
    # as a placeholder; text such as "超过平均周期 50%" or LIKE 'PHASE_%' is
    # doubled so the database receives it unchanged.
    return sql.replace("%", "%%")


def _strip_sql_comments(sql):
    """Remove ``--`` line comments that are not inside a quoted literal."""
    lines = []
    for line in sql.split("\n"):
        quoted, cut = False, None
        index = 0
        while index < len(line):
            char = line[index]
            if char == "'":
                quoted = not quoted
            elif not quoted and line.startswith("--", index):
                cut = index
                break
            index += 1
        kept = line if cut is None else line[:cut]
        if kept.strip():
            lines.append(kept.rstrip())
    return "\n".join(lines)


def collect(period, measurement_date=None, database=None, config=None, progress=None,
            diagnostic_reporter=None):
    """Read fixed V2 facts from one repeatable-read PostgreSQL snapshot.

    Independent statements run with three connections that import the same
    exported snapshot.  A statement is capped at 30 seconds and the whole
    database phase at 60 seconds; completed results survive a timeout and
    remaining queries are cancelled.
    """
    config = config or load_config()
    year = _safe_year(period)
    measured = _measurement_date(period, measurement_date)
    database = database or _database()
    if not database.available:
        error = OpportunityV2Unavailable(_text(getattr(database, "unavailable_reason", lambda: "")()))
        error.phase = "database_connect"
        error.code = "DATABASE_UNAVAILABLE"
        error.diagnostic_message = error.args[0]
        raise error
    started = time.monotonic()
    errors: list[dict] = []
    failure_details: list[str] = []
    query_status: dict[str, str] = {}
    schema = database.config.schema
    statement_timeout = _query_timeout_ms()
    budget = _fetch_budget_seconds()
    total_queries = 9
    completed_queries = 0
    query_catalog: list[dict] = []
    query_specs: dict[str, tuple[str, list]] = {}
    db_config = getattr(database, "config", None)
    db_source = dict(
        source="customer PostgreSQL",
        database=_text(getattr(db_config, "database", "")),
        schema=_text(getattr(db_config, "schema", "") or schema),
        host=_text(getattr(db_config, "host", "")),
        port=getattr(db_config, "port", None),
    )

    def report_query(label, status, duration, error=None, value=None, meta=None):
        nonlocal completed_queries
        completed_queries += 1
        query_status[label] = status
        sql, params = query_specs.get(label, ("", []))
        rows = results.get(label) or []
        meta = dict(meta or {})
        row_meta = _query_result_meta(rows)
        entry = dict(
            executionId=uuid.uuid4().hex,
            label=label, sql=sql, params=list(params), status=status,
            durationSeconds=round(duration, 3),
            durationMs=int(round(duration * 1000)),
            startedAt=meta.get("startedAt") or "",
            finishedAt=meta.get("finishedAt") or "",
            rowCount=len(rows),
            truncated=status == "truncated" or bool(meta.get("truncated")),
            resultHash=row_meta["resultHash"],
            columns=row_meta["columns"],
            sampleRows=row_meta["sampleRows"],
            sampleRowCount=row_meta["sampleRowCount"],
            sampleTruncated=row_meta["sampleTruncated"],
            sampleLimit=row_meta["sampleLimit"],
            database=db_source["database"], schema=db_source["schema"],
            host=db_source["host"], port=db_source["port"],
            source=db_source["source"],
            aggregation=_QUERY_AGGREGATION_NOTES.get(label, ""),
            metricCodes=list(_QUERY_METRICS.get(label, [])),
        )
        if error is not None:
            entry["error"] = {key: error.get(key) for key in
                              ("code", "upstreamCode", "message", "diagnosticId")
                              if error.get(key)}
        query_catalog.append(entry)
        if error is not None:
            entry = dict(stage=label, code=error.get("code") or "QUERY_FAILED",
                         sqlstate=error.get("upstreamCode") or "",
                         durationSeconds=error.get("durationSeconds") or 0)
            failure_details.append(
                f"{label}: {entry['code']}"
                + (f" [{entry['sqlstate']}]" if entry['sqlstate'] else "")
                + (f" {error.get('message')[:300]}" if error.get('message') else "")
            )
            if diagnostic_reporter is not None:
                try:
                    saved = diagnostic_reporter(error)
                    if isinstance(saved, dict) and saved.get("diagnosticId"):
                        entry["diagnosticId"] = saved["diagnosticId"]
                except Exception:  # noqa: BLE001 - diagnostics cannot fail analysis
                    pass
            errors.append(entry)
        _report_progress(
            progress, "fetching", message=f"查询数据库 {completed_queries}/{total_queries}",
            query=label, completed=completed_queries, total=total_queries,
            queryDurationSeconds=round(duration, 3), queryStatus=status,
        )
        return value if value is not None else []

    def _now_iso():
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def run_one(reader, spec):
        label, sql, params = spec
        started_at = _now_iso()
        query_started = time.monotonic()
        try:
            result = reader.run(sql, params, timeout_ms=statement_timeout)
            duration = time.monotonic() - query_started
            status = "truncated" if getattr(result, "truncated", False) else "ok"
            meta = dict(startedAt=started_at, finishedAt=_now_iso(),
                        truncated=status == "truncated")
            if status == "truncated":
                error = dict(phase="database_query", query=label, code="ROW_LIMIT",
                             upstreamCode="", message="row limit reached",
                             durationSeconds=round(duration, 3))
                return label, [dict(row) for row in result.rows], status, duration, error, meta
            return label, [dict(row) for row in result.rows], status, duration, None, meta
        except Exception as exc:  # noqa: BLE001 - report a controlled limitation
            duration = time.monotonic() - query_started
            meta = dict(startedAt=started_at, finishedAt=_now_iso(), truncated=False)
            return label, [], "failed", duration, _query_failure(exc, label, duration), meta

    def run_batch(readers, specs, parallel, deadline, results):
        nonlocal total_queries
        pending = {}
        if parallel and len(readers) > 1 and len(specs) > 1:
            pool = queue.Queue()
            for reader in readers:
                pool.put(reader)

            def work(spec):
                reader = pool.get()
                try:
                    return run_one(reader, spec)
                finally:
                    pool.put(reader)

            executor = ThreadPoolExecutor(max_workers=min(len(readers), len(specs)),
                                          thread_name_prefix="cockpit-v2-db")
            futures = {executor.submit(work, spec): spec[0] for spec in specs}
            pending = dict(futures)
            try:
                while pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    done, _ = wait(set(pending), timeout=remaining, return_when=FIRST_COMPLETED)
                    if not done:
                        break
                    for future in done:
                        label = pending.pop(future)
                        try:
                            item = future.result()
                        except Exception as exc:  # noqa: BLE001 - worker crash
                            duration = 0.0
                            item = (label, [], "failed", duration,
                                    _query_failure(exc, label, duration),
                                    dict(startedAt="", finishedAt="", truncated=False))
                        results[item[0]] = item[1]
                        report_query(item[0], item[2], item[3], item[4], meta=item[5])
                if pending:
                    # Cancel what has not started and ask PostgreSQL to cancel
                    # the running statements.  Results already returned stay.
                    for future in pending:
                        future.cancel()
                    for reader in readers:
                        cancel = getattr(reader, "cancel", None)
                        if callable(cancel):
                            cancel()
                    for label in pending.values():
                        error = dict(phase="database_query", query=label, code="TIMEOUT",
                                     upstreamCode="", message="database fetch budget exhausted",
                                     durationSeconds=round(max(0.0, deadline - time.monotonic()), 3))
                        results[label] = []
                        report_query(label, "timeout", 0, error, meta=dict(startedAt="", finishedAt="", truncated=False))
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
            return

        for spec in specs:
            if time.monotonic() >= deadline:
                remaining_specs = [item for item in specs if item[0] not in results]
                total_queries = max(total_queries, completed_queries + len(remaining_specs))
                for label, _sql, _params in remaining_specs:
                    error = dict(phase="database_query", query=label, code="TIMEOUT",
                                 upstreamCode="", message="database fetch budget exhausted",
                                 durationSeconds=0)
                    results[label] = []
                    report_query(label, "timeout", 0, error, meta=dict(startedAt="", finishedAt="", truncated=False))
                return
            label, rows, status, duration, error, meta = run_one(readers[0], spec)
            results[label] = rows
            report_query(label, status, duration, error, meta=meta)

    # The config contains physical names already validated against the reviewed
    # ontology.  SQL is assembled only from those names and fixed templates.
    target_table = _table(config, "LE06")
    target_cols = _columns(config, "LE06")
    months = [target_cols[f"new_month{i}"] for i in range(1, 13)]
    target_energy_cfg = (config.get("overrides") or {}).get("targetEnergy") or {}
    energy_pattern = _text(target_energy_cfg.get("fieldPattern")) or "new_month{i}_quantity"
    quantities = [target_cols[energy_pattern.replace("{i}", str(i))]
                  for i in range(1, 13)]
    # B01 / BR-Q11: units per GWh come from the ontology SQL parameter
    # target_power_units_per_gwh (kWh ÷ 10^6), not from a hand-written unit.
    target_energy_unit = _text(target_energy_cfg.get("nativeUnit")) or "kWh"
    units_per_gwh = _number(target_energy_cfg.get("unitsPerGwh"))
    target_energy_divisor = (float(units_per_gwh) if units_per_gwh and units_per_gwh > 0 else
                             {"kWh": 1_000_000.0, "MWh": 1_000.0, "GWh": 1.0}.get(target_energy_unit))
    if target_energy_divisor is None:
        raise OpportunityV2Unavailable("本体 B01 电量单位无法换算：" + target_energy_unit)
    amount_count = "+".join(f"COUNT(t.{col})" for col in months)
    energy_count = "+".join(f"COUNT(t.{col})" for col in quantities)
    # B01 (ontology target_rows): keep the latest target per opportunity
    # (an empty opportunity id keeps its own target id) and year.
    target_sql = (
        f"WITH tr AS (SELECT x.*, ROW_NUMBER() OVER (PARTITION BY "
        f"COALESCE(NULLIF(BTRIM(x.{target_cols['new_opportunity_id']}::text), ''), x.{target_cols['new_targetid']}::text), "
        f"x.{target_cols['new_year']} ORDER BY x.{target_cols['createdon']} DESC NULLS LAST, "
        f"x.{target_cols['new_targetid']} DESC NULLS LAST) AS rn "
        f"FROM {target_table} x WHERE x.{target_cols['new_year']} = %s "
        f"AND x.{target_cols['new_targetid']} IS NOT NULL) "
        f"SELECT COALESCE(t.{target_cols['new_producttype_id']}, '') AS product_type_id, "
        f"COALESCE(t.{target_cols['new_account_id']}, '') AS account_id, "
        f"CASE WHEN ({amount_count}) = 0 THEN NULL ELSE "
        f"SUM({'+'.join('COALESCE(t.' + col + ',0)' for col in months)}) END AS amount_yuan, "
        f"CASE WHEN ({energy_count}) = 0 THEN NULL ELSE "
        f"SUM({'+'.join('COALESCE(t.' + col + ',0)' for col in quantities)}) END AS energy_kwh, "
        f"({amount_count}) AS amount_cells, ({energy_count}) AS energy_cells, COUNT(*) AS rows "
        f"FROM tr t WHERE t.rn = 1 "
        f"GROUP BY 1,2"
    )

    product_table = _table(config, "LE12")
    product_cols = _columns(config, "LE12")

    opp_table = _table(config, "LE01")
    month_table = _table(config, "LE02")
    account_table = _table(config, "LE05")
    oc = _columns(config, "LE01")
    mc = _columns(config, "LE02")
    ac = _columns(config, "LE05")
    energy_cfg = (config.get("overrides") or {}).get("electricitySource") or {}
    energy_mode = _text(energy_cfg.get("mode")) or "field"
    energy_unit = _text(energy_cfg.get("nativeUnit"))
    energy_divisor = {"Wh": 1_000_000_000.0, "kWh": 1_000_000.0,
                      "MWh": 1_000.0, "GWh": 1.0}.get(energy_unit)
    if energy_divisor is None:
        raise OpportunityV2Unavailable("本体 B02 电量单位无法换算：" + (energy_unit or "未定义"))
    if energy_mode == "amount_div_price":
        amount_field = _text(energy_cfg.get("amountField")) or "new_forecast_amt_rmb"
        price_field = _text(energy_cfg.get("priceField")) or "new_whprice"
        for name, value in (("金额", amount_field), ("单价", price_field)):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
                raise OpportunityV2Unavailable(f"本体 B02 未定义合法的电量{name}字段")
            if value not in mc:
                raise OpportunityV2Unavailable(
                    f"本体 B02 电量{name}字段未在运行时字段映射中：{value}")
        energy_gwh_expr = (f"SUM(m.{mc[amount_field]} / NULLIF(m.{mc[price_field]}, 0)) "
                           f"/ {energy_divisor}")
        energy_rows_expr = (f"COUNT(CASE WHEN m.{mc[amount_field]} IS NOT NULL "
                            f"AND m.{mc[price_field]} IS NOT NULL "
                            f"AND m.{mc[price_field]} <> 0 THEN 1 END)")
        energy_field = f"{amount_field}/{price_field}"
    else:
        energy_field = _text(energy_cfg.get("field"))
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", energy_field):
            raise OpportunityV2Unavailable("本体 B02 未定义合法的电量字段")
        if energy_field not in mc:
            raise OpportunityV2Unavailable("本体 B02 电量字段未在运行时字段映射中：" + energy_field)
        energy_gwh_expr = f"SUM(m.{mc[energy_field]}) / {energy_divisor}"
        energy_rows_expr = f"COUNT(m.{mc[energy_field]})"
    # Ontology opportunity_rows / account_rows: one row per id, latest first.
    opp_src = (f"(SELECT DISTINCT ON (x.{oc['opportunityid']}) x.* FROM {opp_table} x "
               f"WHERE NULLIF(BTRIM(x.{oc['opportunityid']}::text), '') IS NOT NULL "
               f"ORDER BY x.{oc['opportunityid']}, x.{oc['modifiedon']} DESC NULLS LAST, "
               f"x.{oc['createdon']} DESC NULLS LAST)")
    account_src = (f"(SELECT DISTINCT ON (y.{ac['accountid']}) y.* FROM {account_table} y "
                   f"WHERE NULLIF(BTRIM(y.{ac['accountid']}::text), '') IS NOT NULL "
                   f"ORDER BY y.{ac['accountid']}, y.{ac['modifiedon']} DESC NULLS LAST, "
                   f"y.{ac['createdon']} DESC NULLS LAST)")
    # BR-Q01 / B02 forecast_rows: within the year, the latest version of each
    # opportunity-month, forecast amount only (no actuals), no state filter.
    forecast_cte = (
        f"fr AS (SELECT x.*, ROW_NUMBER() OVER (PARTITION BY x.{mc['new_opportunity_id']}, "
        f"date_trunc('month', x.{mc['new_accountdate']}::timestamp) ORDER BY x.{mc['createdon']} DESC NULLS LAST, "
        f"x.{mc['modifiedon']} DESC NULLS LAST, x.{mc['new_oppmonthid']} DESC NULLS LAST) AS rn "
        f"FROM {month_table} x WHERE NULLIF(BTRIM(x.{mc['new_oppmonthid']}::text), '') IS NOT NULL "
        f"AND NULLIF(BTRIM(x.{mc['new_opportunity_id']}::text), '') IS NOT NULL "
        f"AND EXTRACT(YEAR FROM x.{mc['new_accountdate']})::int = %s), "
        f"agg AS (SELECT m.{mc['new_opportunity_id']} AS opportunity_id, "
        f"SUM(m.{mc['new_forecast_amt_rmb']}) AS amount_yuan, "
        f"SUM(m.{mc['new_forecast_amt_rmb']}) AS forecast_amount_full_yuan, "
        f"{energy_gwh_expr} AS energy_gwh, COUNT(*) AS month_rows, {energy_rows_expr} AS energy_rows "
        f"FROM fr m WHERE m.rn = 1 GROUP BY 1)"
    )
    # Ontology cutoff is the end of the measurement day (created_at <= cutoff,
    # an unknown creation time is kept).
    created_ok = f"(o.{oc['createdon']} IS NULL OR o.{oc['createdon']} < (%s::date + 1))"
    # BR-Q02: an opportunity is signed when at least one order is linked to it
    # through order detail (明细.new_opportunity_id → 明细.salesorderid →
    # 订单.salesorderid).  No approval, cancel-state or date filter, and the
    # contract-confirmation enum is not used.
    order_table = _table(config, "LE07")
    detail_table = _table(config, "LE08")
    order_cols = _columns(config, "LE07")
    detail_cols = _columns(config, "LE08")
    # BR-Q04 储能客户范围: latest opportunity owners → their teams → every member
    # of those teams → customers owned by one of those members.  A customer
    # needs no opportunity of its own and no creation-year filter applies.
    storage_cfg = (config.get("overrides") or {}).get("storageCustomerScope") or {}
    storage_scope = bool(storage_cfg.get("enabled"))
    storage_flag = storage_join = storage_account_filter = ""
    if storage_scope:
        st = _columns(config, "LE10")
        sm = _columns(config, "LE11")
        owner_field = _text(storage_cfg.get("ownerField"))
        account_owner_field = _text(storage_cfg.get("accountOwnerField"))
        if owner_field not in oc or account_owner_field not in ac or not {"teamid"} <= set(st) \
                or not {"teamid", "systemuserid"} <= set(sm):
            raise OpportunityV2Unavailable("本体 BR-Q04 储能客户范围缺少字段映射")
        storage_sql = (
            f"(SELECT sa.{ac['accountid']}::text AS account_id FROM {account_src} sa "
            f"WHERE sa.{ac[account_owner_field]}::text IN ("
            f"SELECT su.{sm['systemuserid']}::text FROM {_table(config, 'LE11')} su "
            f"WHERE NULLIF(BTRIM(su.{sm['systemuserid']}::text), '') IS NOT NULL "
            f"AND su.{sm['teamid']}::text IN ("
            f"SELECT stm.{sm['teamid']}::text FROM {_table(config, 'LE11')} stm "
            f"JOIN {_table(config, 'LE10')} stt ON stt.{st['teamid']} = stm.{sm['teamid']} "
            f"WHERE NULLIF(BTRIM(stm.{sm['teamid']}::text), '') IS NOT NULL "
            f"AND stm.{sm['systemuserid']}::text IN ("
            f"SELECT sow.{oc[owner_field]}::text FROM {opp_src} sow "
            f"WHERE NULLIF(BTRIM(sow.{oc[owner_field]}::text), '') IS NOT NULL))))"
        )
        storage_flag = " (sc.account_id IS NOT NULL) AS storage_customer,"
        storage_join = f" LEFT JOIN {storage_sql} sc ON sc.account_id = o.{oc['parentaccountid']}::text"
        storage_account_filter = f" AND a.{ac['accountid']}::text IN (SELECT account_id FROM {storage_sql} sc)"
        # R08: the customer × product target carries whether the customer is in scope.
        target_sql = (f"SELECT q.*, (q.account_id::text IN (SELECT account_id FROM {storage_sql} sc)) "
                      f"AS storage_customer FROM ({target_sql}) q")
    signed_expr = (
        f"(CASE WHEN EXISTS (SELECT 1 FROM {detail_table} sd "
        f"JOIN {order_table} so ON so.{order_cols['salesorderid']} = sd.{detail_cols['salesorderid']} "
        f"WHERE sd.{detail_cols['new_opportunity_id']} = o.{oc['opportunityid']}) "
        f"THEN '1' ELSE '0' END)"
    )
    opp_sql = (
        f"WITH {forecast_cte} SELECT o.{oc['opportunityid']} AS opportunity_id, o.{oc['name']} AS name, "
        f" COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f" COALESCE(a.{ac['name']}, '') AS account_name, "
        f" COALESCE(a.{ac['new_accountlevel']}::text, '') AS account_level, "
        f"{storage_flag}"
        f" COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f" COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f" COALESCE(o.{oc['new_approvalstatus_acneed']}, '') AS acneed_status, "
        f" COALESCE(o.{oc['new_opportunitystatus']}, '') AS opportunity_status, "
        f" {signed_expr} AS contract_confirmation, "
        f" COALESCE(o.{oc['new_demandinput']}::text, '') AS demand_input, "
        f" o.{oc['createdon']} AS created_at, o.{oc['new_stage1enddate']} AS stage1_end, "
        f" o.{oc['new_stage2enddate']} AS stage2_end, o.{oc['new_stage3enddate']} AS stage3_end, "
        f" o.{oc['new_stage4enddate']} AS stage4_end, o.{oc['new_stage5enddate']} AS stage5_end, "
        f" COALESCE(o.{oc['ownerid']}, '') AS owner_id, agg.amount_yuan, "
        f" agg.forecast_amount_full_yuan, agg.energy_gwh, "
        f" agg.month_rows, agg.energy_rows "
        f" FROM {opp_src} o LEFT JOIN agg ON o.{oc['opportunityid']} = agg.opportunity_id "
        f" LEFT JOIN {account_src} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f"{storage_join}"
        f" WHERE {created_ok}"
    )

    all_opp_sql = (
        f"SELECT o.{oc['opportunityid']} AS opportunity_id, o.{oc['name']} AS name, "
        f"COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f"COALESCE(a.{ac['new_accountlevel']}::text, '') AS account_level, "
        f"COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f"COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f"COALESCE(o.{oc['new_opportunitystatus']}, '') AS opportunity_status, "
        f"{signed_expr} AS contract_confirmation, "
        f"o.{oc['createdon']} AS created_at, o.{oc['new_stage1enddate']} AS stage1_end, "
        f"o.{oc['new_stage2enddate']} AS stage2_end, o.{oc['new_stage3enddate']} AS stage3_end, "
        f"o.{oc['new_stage4enddate']} AS stage4_end, o.{oc['new_stage5enddate']} AS stage5_end "
        f"FROM {opp_src} o LEFT JOIN {account_src} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f"WHERE {created_ok}"
    )

    # Full aggregate fallback for truncated detail rows.  A truncated list can
    # still be displayed, but its partial sums must never drive risk rules.
    aggregate_sql = (
        f"WITH {forecast_cte} SELECT {signed_expr} AS contract_raw, "
        f" COALESCE(a.{ac['new_accountlevel']}::text, '') AS account_level, "
        f" COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f" COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f" COALESCE(a.{ac['name']}, '') AS account_name, "
        f" COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f" {'(sc.account_id IS NOT NULL)' if storage_scope else 'NULL::boolean'} AS storage_customer, "
        f" COUNT(*) AS opportunity_count, "
        f" SUM(agg.amount_yuan) AS amount_yuan, SUM(agg.forecast_amount_full_yuan) AS forecast_amount_full_yuan, "
        f" SUM(agg.energy_gwh) AS energy_gwh, SUM(agg.month_rows) AS month_rows, "
        f" SUM(agg.energy_rows) AS energy_rows "
        f" FROM {opp_src} o LEFT JOIN agg ON o.{oc['opportunityid']} = agg.opportunity_id "
        f" LEFT JOIN {account_src} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f"{storage_join}"
        f" WHERE {created_ok} "
        f" GROUP BY 1,2,3,4,5,6,7"
    )

    strategic_ok, strategic_reason = _strategic_scope(config)
    strategic_levels = ([str(value) for value in
                         _customer_tier_config(config).get("strategic") or []]
                        if strategic_ok else [])
    if strategic_ok and not strategic_levels:
        raise OpportunityV2Unavailable("本体未给出可执行的战略客户等级映射")
    strategic_level_slots = ",".join(["%s"] * len(strategic_levels))
    activity = (config.get("overrides") or {}).get("recentActivity") or {}
    activity_fields = activity.get("accountFields") or {}
    lead_table = _physical_table_name(activity.get("leadTable"))
    lead_id = _text(activity.get("leadIdField"))
    lead_account = _text(activity.get("leadAccountField"))
    lead_created = _text(activity.get("leadCreatedField"))
    lead_progress_table = _physical_table_name(activity.get("leadProgressTable"))
    lead_progress_lead = _text(activity.get("leadProgressLeadField"))
    lead_progress_created = _text(activity.get("leadProgressCreatedField"))
    for name in (lead_id, lead_account, lead_created, lead_progress_lead, lead_progress_created):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise OpportunityV2Unavailable("V3 近期活动来源缺少合法字段映射")
    accounts_sql = (
        f"SELECT a.{ac['accountid']} AS account_id, a.{ac['name']} AS name, "
        f"a.{ac['new_accountlevel']} AS account_level, a.{ac['createdon']} AS created_at, "
        f"a.{ac[activity_fields['lastVisitAt']]} AS last_visit_at, "
        f"a.{ac[activity_fields['lastVisitDays']]} AS last_visit_days, "
        f"a.{ac[activity_fields['latestActivityAt']]} AS latest_activity_at, "
        f"a.{ac[activity_fields['originatingLeadId']]} AS originating_lead_id, "
        f"la.latest_lead_at, lp.latest_lead_progress_at, "
        f"COALESCE(cov.opportunity_count, 0) AS opportunity_count "
        f"FROM {account_src} a "
        f"LEFT JOIN (SELECT z.{oc['parentaccountid']} AS account_id, "
        f"           COUNT(DISTINCT z.{oc['opportunityid']}) AS opportunity_count FROM {opp_table} z "
        f"           WHERE z.{oc['parentaccountid']} IS NOT NULL GROUP BY 1) cov "
        f"       ON cov.account_id = a.{ac['accountid']} "
        f"LEFT JOIN (SELECT l.{lead_account} AS account_id, MAX(l.{lead_created}) AS latest_lead_at "
        f"           FROM {lead_table} l WHERE l.{lead_created} <= %s AND l.{lead_account} IS NOT NULL "
        f"           GROUP BY 1) la ON la.account_id = a.{ac['accountid']} "
        f"LEFT JOIN (SELECT l.{lead_account} AS account_id, MAX(p.{lead_progress_created}) AS latest_lead_progress_at "
        f"           FROM {lead_table} l JOIN {lead_progress_table} p "
        f"           ON p.{lead_progress_lead} = l.{lead_id} "
        f"           WHERE p.{lead_progress_created} <= %s AND l.{lead_account} IS NOT NULL "
        f"           GROUP BY 1) lp ON lp.account_id = a.{ac['accountid']} "
        f"WHERE a.{ac['new_accountlevel']}::text IN ({strategic_level_slots})"
        f"{storage_account_filter}"
    )

    # Bid data is read only while the ontology still carries a bid risk; the
    # current ontology has neither the risks nor the LE09 bid table.
    bid_query = bool({"RK08", "RK09"} & set(config.get("risks") or {}))
    if bid_query:
        bid_table = _table(config, "LE09")
        bid_cols = _columns(config, "LE09")
        bid_sql = (
            f"SELECT b.{bid_cols['seq_no']} AS seq_no, b.{bid_cols['project_name']} AS project_name, "
            f"b.{bid_cols['input_time']} AS input_time, b.{bid_cols['bid_open_time']} AS bid_open_time, "
            f"b.{bid_cols['winner_announce_time']} AS winner_time, b.{bid_cols['is_awarded']} AS is_awarded, "
            f"COALESCE(b.{bid_cols['bid_open_result']}, '') AS bid_open_result, "
            f"b.{bid_cols['bid_amount']} AS bid_amount, b.{bid_cols['energy_mwh']} AS energy_mwh "
            f"FROM {bid_table} b WHERE b.{bid_cols['input_time']} <= %s"
        )

    progress_table = _table(config, "LE04")
    pc = _columns(config, "LE04")
    progress_sql = (
        f"SELECT p.{pc['new_projectprocessid']} AS progress_id, "
        f"p.{pc['new_opportunity_id']} AS opportunity_id, "
        f"COALESCE(p.{pc['new_desc']}, '') AS description, "
        f"p.{pc['new_sdate']} AS start_at, p.{pc['new_edate']} AS end_at, "
        f"COALESCE(p.{pc['new_question_resource']}, '') AS question_resource, "
        f"p.{pc['new_projectstage']} AS project_stage "
        f"FROM {progress_table} p WHERE p.{pc['new_sdate']} <= %s "
        f"OR (p.{pc['new_sdate']} IS NULL AND p.{pc['new_edate']} <= %s)"
    )

    # Order counts per opportunity (BR-Q02 evidence; signing itself is signed_expr).
    order_sql = (
        f"SELECT d.{detail_cols['new_opportunity_id']} AS opportunity_id, "
        f"COUNT(DISTINCT o.{order_cols['salesorderid']}) AS order_count, "
        f"SUM(o.{order_cols['new_contract_amt']}) AS order_amount "
        f"FROM {detail_table} d JOIN {order_table} o ON o.{order_cols['salesorderid']} = d.{detail_cols['salesorderid']} "
        f"WHERE d.{detail_cols['new_opportunity_id']} IS NOT NULL "
        f"GROUP BY 1"
    )

    team_table = _table(config, "LE10")
    member_table = _table(config, "LE11")
    tc = _columns(config, "LE10")
    mc2 = _columns(config, "LE11")
    team_sql = (
        f"SELECT tm.{mc2['systemuserid']} AS user_id, MIN(t.{tc['name']}) AS team_name "
        f"FROM {member_table} tm JOIN {team_table} t ON t.{tc['teamid']} = tm.{mc2['teamid']} "
        f"GROUP BY 1"
    )

    # All reads share one repeatable-read snapshot.  Calling database.run for
    # each query would silently span several snapshots and could combine target,
    # forecast and bid facts observed at different times.  The first batch is
    # independent and runs with up to three snapshot-sharing connections.
    product_sql = (
        f"SELECT p.{product_cols['new_product_typeid']} AS product_type_id, "
        f"p.{product_cols['new_accproducttype']} AS product_type, p.{product_cols['new_name']} AS name "
        f"FROM {product_table} p"
    )
    specs = [
        ("销售目标", target_sql, [year]),
        ("产品类型", product_sql, []),
        ("商机预测", opp_sql, [year, measured]),
        ("全部商机", all_opp_sql, [measured]),
        ("项目进展", progress_sql, [measured, measured]),
        ("订单关联", order_sql, []),
        ("产品团队", team_sql, []),
    ]
    if bid_query:
        specs.insert(4, ("投标", bid_sql, [measured]))
    # RC04 is judged on the ontology's own C05 query (product team actual
    # sales minus annual target); it is not a core query.
    team_gap_sql = _ontology_metric_sql(config, "C05", year, measured, schema)
    if team_gap_sql:
        specs.append(("产品部销售缺口", team_gap_sql, []))
    if strategic_ok:
        specs.insert(4, ("客户", accounts_sql, [measured, measured] + strategic_levels))
    else:
        query_status["客户"] = "unavailable"
        query_catalog.append(dict(
            executionId=uuid.uuid4().hex,
            label="客户", sql="", params=[], status="unavailable",
            durationSeconds=0.0, durationMs=0, startedAt="", finishedAt="",
            rowCount=0, truncated=False,
            resultHash=hashlib.sha256(b"[]").hexdigest(),
            columns=[], sampleRows=[], sampleRowCount=0,
            sampleTruncated=False, sampleLimit=_query_sample_limit(),
            database=db_source["database"], schema=db_source["schema"],
            host=db_source["host"], port=db_source["port"],
            source=db_source["source"], aggregation=_QUERY_AGGREGATION_NOTES.get("客户", ""),
            reason=f"战略客户名单未配置：{strategic_reason}",
        ))
    total_queries = len(specs)
    query_specs.update({label: (sql, params) for label, sql, params in specs})
    query_specs["商机聚合"] = (aggregate_sql, [year, measured])
    deadline = started + budget
    results = {}
    with _reader_group(database, workers=3) as (readers, parallel):
        run_batch(readers, specs, parallel, deadline, results)
        aggregate_rows = []
        if (query_status.get("商机预测") == "truncated"
                or query_status.get("全部商机") == "truncated"):
            total_queries = max(total_queries, completed_queries + 1)
            run_batch(readers[:1], [("商机聚合", aggregate_sql, [year, measured])],
                      False, deadline, results)
            aggregate_rows = results.get("商机聚合", [])

    target_rows = results.get("销售目标", [])
    product_rows = results.get("产品类型", [])
    opp_rows = results.get("商机预测", [])
    all_opp_rows = results.get("全部商机", [])
    account_rows = results.get("客户", [])
    bid_rows_raw = results.get("投标", [])
    progress_rows = results.get("项目进展", [])
    order_rows = results.get("订单关联", [])
    team_rows = results.get("产品团队", [])
    team_gap_rows = [dict(team=_text(row.get("产品团队")), gapAmount=_number(row.get("金额_亿元")),
                          gapEnergy=_number(row.get("电量_GWh")), status=_text(row.get("计算说明状态")))
                     for row in results.get("产品部销售缺口", []) if isinstance(row, dict)]

    product_types = {_text(row.get("product_type_id")): _text(row.get("product_type"))
                     for row in product_rows}

    targets = dict(amount=None, energy=None, rows=0, amountCells=0, energyCells=0,
                   byProduct=defaultdict(lambda: dict(amount=0.0, energy=0.0, rows=0)),
                   byAccount={}, byAccountProduct={})
    for row in target_rows:
        amount = _number(row.get("amount_yuan"))
        energy = _number(row.get("energy_kwh"))
        energy = energy / target_energy_divisor if energy is not None else None
        rows_count = int(_number(row.get("rows")) or 0)
        targets["amountCells"] += int(_number(row.get("amount_cells")) or 0)
        targets["energyCells"] += int(_number(row.get("energy_cells")) or 0)
        product_id = _text(row.get("product_type_id"))
        product = product_types.get(product_id, product_id)
        key = _product_key(product)
        if amount is not None:
            targets["amount"] = (targets["amount"] or 0.0) + amount
        if energy is not None:
            targets["energy"] = (targets["energy"] or 0.0) + energy
        targets["rows"] += rows_count
        bucket = targets["byProduct"][key]
        bucket["amount"] += amount or 0.0
        bucket["energy"] += energy or 0.0
        bucket["rows"] += rows_count
        account_id = _text(row.get("account_id"))
        if account_id:
            current = targets["byAccount"].setdefault(account_id, dict(amount=0.0, energy=0.0, rows=0))
            current["amount"] += amount or 0.0
            current["energy"] += energy or 0.0
            current["rows"] += rows_count
            pair = targets["byAccountProduct"].setdefault(
                f"{account_id}|{key}", dict(accountId=account_id, productType=key,
                                            amount=None, energy=None))
            if row.get("storage_customer") is not None:
                pair["storageCustomer"] = bool(row.get("storage_customer"))
            if amount is not None:
                pair["amount"] = (pair["amount"] or 0.0) + amount
            if energy is not None:
                pair["energy"] = (pair["energy"] or 0.0) + energy
    targets["amount"] = (round(targets["amount"] / 100_000_000.0, 6)
                         if targets["amount"] is not None else None)
    targets["energy"] = round(targets["energy"], 6) if targets["energy"] is not None else None
    for bucket in list(targets["byProduct"].values()) + list(targets["byAccount"].values()):
        bucket["amount"] = round((bucket.get("amount") or 0.0) / 100_000_000.0, 6)
        bucket["energy"] = round(bucket.get("energy") or 0.0, 6)
    for pair in targets["byAccountProduct"].values():
        pair["amount"] = (round(pair["amount"] / 100_000_000.0, 6)
                          if pair["amount"] is not None else None)
        pair["energy"] = round(pair["energy"], 6) if pair["energy"] is not None else None

    orders = {_text(row.get("opportunity_id")): dict(
        count=int(_number(row.get("order_count")) or 0),
        amount=_round((_number(row.get("order_amount")) or 0.0) / 100_000_000.0, 6),
    ) for row in order_rows}
    departments = {_text(row.get("user_id")): _text(row.get("team_name")) for row in team_rows}

    opportunity_aggregates = []
    for row in aggregate_rows:
        contract_raw = _text(row.get("contract_raw"))
        level = _text(row.get("account_level"))
        product = _text(row.get("product_type"))
        opportunity_aggregates.append(dict(
            contract=("confirmed" if contract_raw == "1" else
                      "not_confirmed" if contract_raw == "0" else "unknown"),
            tier=_customer_tier(level, config),
            accountLevel=level,
            productType=_product_key(product),
            accountId=_text(row.get("account_id")),
            accountName=_text(row.get("account_name")),
            stage=_text(row.get("process_stage")),
            storageCustomer=(bool(row.get("storage_customer"))
                             if row.get("storage_customer") is not None else None),
            count=int(_number(row.get("opportunity_count")) or 0),
            amount=(_round(_number(row.get("amount_yuan")) / 100_000_000.0, 6)
                    if row.get("amount_yuan") is not None else None),
            amountFull=(_round(_number(row.get("forecast_amount_full_yuan")) / 100_000_000.0, 6)
                        if row.get("forecast_amount_full_yuan") is not None else None),
            energy=_round(row.get("energy_gwh"), 6),
            monthRows=int(_number(row.get("month_rows")) or 0),
            energyRows=int(_number(row.get("energy_rows")) or 0),
        ))

    opportunities = []
    for row in opp_rows:
        opp_id = _text(row.get("opportunity_id"))
        if not opp_id:
            continue
        level = _text(row.get("account_level"))
        tier = _customer_tier(level, config)
        contract_raw = _text(row.get("contract_confirmation"))
        contract = "confirmed" if contract_raw == "1" else ("not_confirmed" if contract_raw == "0" else "unknown")
        product = _text(row.get("product_type"))
        stage = _text(row.get("process_stage"))
        month_rows = int(_number(row.get("month_rows")) or 0)
        energy_rows = int(_number(row.get("energy_rows")) or 0)
        opportunities.append(dict(
            id=opp_id,
            name=_text(row.get("name")),
            accountId=_text(row.get("account_id")),
            accountName=_text(row.get("account_name")),
            accountLevel=level,
            tier=tier,
            storageCustomer=(bool(row.get("storage_customer"))
                             if row.get("storage_customer") is not None else None),
            productType=_product_key(product),
            productName=_product_name(_product_key(product), config),
            stage=stage,
            stageName=_stage_name(stage, config),
            acneed=_text(row.get("acneed_status")),
            demandInput=_text(row.get("demand_input")),
            status=_text(row.get("opportunity_status")),
            contract=contract,
            contractRaw=contract_raw,
            createdAt=_iso(_day(row.get("created_at"))),
            stage1End=_iso(_day(row.get("stage1_end"))),
            stage2End=_iso(_day(row.get("stage2_end"))),
            stage3End=_iso(_day(row.get("stage3_end"))),
            stage4End=_iso(_day(row.get("stage4_end"))),
            stage5End=_iso(_day(row.get("stage5_end"))),
            forecastAmount=_round((_number(row.get("amount_yuan")) or 0.0) / 100_000_000.0, 6) if row.get("amount_yuan") is not None else None,
            forecastAmountFull=_round((_number(row.get("forecast_amount_full_yuan")) or 0.0) / 100_000_000.0, 6) if row.get("forecast_amount_full_yuan") is not None else None,
            forecastEnergy=_round(row.get("energy_gwh"), 6),
            energyCoverage=_div(energy_rows, month_rows) if month_rows else None,
            monthRows=month_rows,
            energyRows=energy_rows,
            orderCount=orders.get(opp_id, {}).get("count", 0),
            orderAmount=orders.get(opp_id, {}).get("amount"),
            department=departments.get(_text(row.get("owner_id")), ""),
        ))

    bids = []
    for row in bid_rows_raw:
        input_day = _day(row.get("input_time"))
        winner_day = _day(row.get("winner_time"))
        cycle = (winner_day or measured) - input_day if input_day else None
        bids.append(dict(
            id=_text(row.get("seq_no")),
            name=_text(row.get("project_name")).strip(),
            inputAt=_iso(input_day),
            winnerAt=_iso(winner_day),
            awarded=_text(row.get("is_awarded")),
            result=_text(row.get("bid_open_result")),
            amount=_round((_number(row.get("bid_amount")) or 0.0) / 100_000_000.0, 6) if row.get("bid_amount") is not None else None,
            energy=_round((_number(row.get("energy_mwh")) or 0.0) / 1000.0, 6) if row.get("energy_mwh") is not None else None,
            cycleDays=cycle.days if cycle and cycle.days >= 0 else None,
            inProgress=bool(input_day and not winner_day),
        ))

    progress = defaultdict(list)
    for row in progress_rows:
        opp_id = _text(row.get("opportunity_id"))
        if not opp_id:
            continue
        progress[opp_id].append(dict(
            id=_text(row.get("progress_id")),
            description=_text(row.get("description")),
            startAt=_iso(_day(row.get("start_at"))),
            endAt=_iso(_day(row.get("end_at"))),
            questionResource=_text(row.get("question_resource")),
            projectStage=_text(row.get("project_stage")),
        ))
    for values in progress.values():
        values.sort(key=lambda item: item.get("startAt") or "", reverse=True)

    accounts = [dict(
        id=_text(row.get("account_id")),
        name=_text(row.get("name")),
        level=_text(row.get("account_level")),
        tier=_customer_tier(row.get("account_level"), config),
        createdAt=_iso(_day(row.get("created_at"))),
        lastVisitAt=_iso(_day(row.get("last_visit_at"))),
        lastVisitDays=int(_number(row.get("last_visit_days"))) if _number(row.get("last_visit_days")) is not None else None,
        latestActivityAt=_iso(_day(row.get("latest_activity_at"))),
        originatingLeadId=_text(row.get("originating_lead_id")),
        latestLeadAt=_iso(_day(row.get("latest_lead_at"))),
        latestLeadProgressAt=_iso(_day(row.get("latest_lead_progress_at"))),
        opportunityCount=int(_number(row.get("opportunity_count")) or 0),
    ) for row in account_rows if _text(row.get("account_id"))]

    all_opportunities = []
    for row in all_opp_rows:
        opp_id = _text(row.get("opportunity_id"))
        if not opp_id:
            continue
        level = _text(row.get("account_level"))
        contract_raw = _text(row.get("contract_confirmation"))
        all_opportunities.append(dict(
            id=opp_id,
            name=_text(row.get("name")),
            accountId=_text(row.get("account_id")),
            accountLevel=level,
            tier=_customer_tier(level, config),
            productType=_product_key(row.get("product_type")),
            stage=_text(row.get("process_stage")),
            status=_text(row.get("opportunity_status")),
            contract=("confirmed" if contract_raw == "1" else
                      "not_confirmed" if contract_raw == "0" else "unknown"),
            createdAt=_iso(_day(row.get("created_at"))),
            stage1End=_iso(_day(row.get("stage1_end"))),
            stage2End=_iso(_day(row.get("stage2_end"))),
            stage3End=_iso(_day(row.get("stage3_end"))),
            stage4End=_iso(_day(row.get("stage4_end"))),
            stage5End=_iso(_day(row.get("stage5_end"))),
        ))

    core_rows = bool(target_rows or opp_rows or all_opp_rows or account_rows)
    if errors and not core_rows:
        labels = "、".join(sorted({item.get("stage") or item.get("code") or "未知" for item in errors}))
        error = OpportunityV2Unavailable("商机 V3 核心取数失败且无可保留证据：" + labels)
        error.phase = "database_query"
        error.code = "CORE_FETCH_FAILED"
        error.diagnostic_message = "；".join(failure_details)[:2400]
        error.query_errors = list(errors)
        raise error

    return dict(
        period=str(year),
        measurementDate=measured.isoformat(),
        productTeamGaps=team_gap_rows,
        productTeamGapStatus=query_status.get("产品部销售缺口", "unavailable" if not team_gap_sql else ""),
        targets=targets,
        productTypes=product_types,
        targetEnergyDivisor=target_energy_divisor,
        opportunities=opportunities,
        allOpportunities=all_opportunities,
        accounts=accounts,
        bids=bids,
        progress=dict(progress),
        departments=departments,
        opportunityAggregates=opportunity_aggregates,
        aggregatesComplete=(not (query_status.get("商机预测") == "truncated"
                                 or query_status.get("全部商机") == "truncated")
                            or query_status.get("商机聚合") == "ok"),
        detailComplete=query_status.get("商机预测") != "truncated",
        allOpportunitiesComplete=query_status.get("全部商机") != "truncated",
        accountsComplete=query_status.get("客户") == "ok",
        bidsComplete=query_status.get("投标") != "truncated",
        strategicScope=dict(available=strategic_ok, reason=strategic_reason),
        errors=errors,
        queryDiagnostics=[dict(item) for item in errors],
        queryStatus=query_status,
        schema=schema,
        fetchBudgetSeconds=budget,
        queryTimeoutMs=statement_timeout,
        queryCatalog=query_catalog,
        fetchedAt=time.time(),
        durationSeconds=round(time.monotonic() - started, 3),
    )


def _avg(values):
    found = [_number(value) for value in values]
    found = [value for value in found if value is not None and value >= 0]
    return sum(found) / len(found) if found else None


def _product_key(value):
    """Ontology product mapping: '1'/'电芯' → 1, '2'/'PACK' → 2, else unknown."""
    text = _text(value)
    return "1" if text in {"1", "电芯"} else "2" if text in {"2", "PACK"} else "unknown"


def _in_storage(item):
    """BR-Q04: inside the 储能客户名单 unless the query said otherwise.

    Inputs collected without the scope (no flag) are not narrowed.
    """
    return item.get("storageCustomer") is not False


def _stage_completed(start, finish, measured):
    """BR-Q06 completed_days: a real start and a real end not before it."""
    if not start or start > measured or not finish or finish < start:
        return None
    return (finish - start).days


def _stage_elapsed(start, finish, measured):
    """Ontology stage_facts: an unfinished stage, or one finishing after the
    cutoff, runs to the cutoff; inverted dates are invalid (None)."""
    if not start or start > measured:
        return None
    end = finish if finish and finish <= measured else measured
    if finish and finish < start:
        return None
    return (end - start).days


def _p0_cycle(opp, measured):
    # P0 = createdon → new_stage1enddate (ontology P0-01).
    return _stage_elapsed(_day(opp.get("createdAt")), _day(opp.get("stage1End")), measured)


def _p2_cycle(opp, measured):
    # P2 = new_stage2enddate → new_stage3enddate (ontology P2-01).
    return _stage_elapsed(_day(opp.get("stage2End")), _day(opp.get("stage3End")), measured)


def _tier_label(tier):
    return {"strategic": "战略", "priority": "重点", "general": "一般"}.get(tier, "未分类")


def _level_for_gap(rate, thresholds):
    if rate is None:
        return "中"
    if rate >= thresholds["gapRateHigh"]:
        return "高"
    if rate >= thresholds["gapRateMedium"]:
        return "中"
    return "低"


def _risk_name(config, code, fallback=""):
    """The risk's name as the ontology's 风险 sheet states it."""
    return _text(((config.get("risks") or {}).get(code) or {}).get("name")) or fallback


def _risk(code, name, level, title, description, metric_codes, evidence_ids, impact, objects):
    return dict(code=code, name=name, level=level, levelRank=_LEVEL_RANK.get(level, 9),
                title=title, description=description, metricCodes=list(dict.fromkeys(metric_codes)),
                evidenceIds=list(dict.fromkeys(evidence_ids))[:20], impact=impact, objects=list(objects))


def _cause_rule_outcomes(*, candidates, data, thresholds, source_ok, unsigned, opps, late_p0,
                         overall_p0, p2_mean_known, focus_ratio, rest_ratio,
                         product_pending_ratio, no_opportunity, activity_source_ready, progress,
                         strategic_pending, record, fact):
    """Settle every ontology cause rule: triggered, not_triggered, insufficient
    or not_applicable.

    ``insufficient`` means the rule cannot be decided from structured data;
    the judgement step then asks the model about that cause alone.
    """
    def outcome(code, status, *, reason, description="", evidence=(), observed=(), missing=()):
        spec = candidates.get(code) or {}
        return dict(code=code, ruleStatus=status, reason=reason,
                    description=description or spec.get("description") or "",
                    kind=spec.get("kind") or "hypothesis",
                    evidenceIds=list(dict.fromkeys(e for e in (list(evidence) or spec.get("evidence") or []) if e))[:20],
                    observed=list(observed), missingEvidence=list(missing or spec.get("missingEvidence") or []))

    out = {}
    opportunities_ok = source_ok("商机预测") or bool(opps)
    out["RC01"] = (outcome("RC01", "triggered", reason="存在未签单的战略客户 P0 商机")
                   if "RC01" in candidates else
                   outcome("RC01", "not_triggered", reason="没有未签单的战略客户 P0 商机")
                   if opportunities_ok else
                   outcome("RC01", "insufficient", reason="商机数据未取到", missing=["商机预测"]))
    if not strategic_pending:
        out["RC02"] = outcome("RC02", "not_applicable", reason="没有待投标的战略客户商机")
    else:
        # The ontology has no structured prerequisite fields (C02 is NULL):
        # the rule cannot settle this cause, the model reads progress texts.
        samples = []
        for opp in strategic_pending[:8]:
            for item in (progress.get(opp.get("id")) or [])[:2]:
                text = f"{item.get('description') or ''}；{item.get('questionResource') or ''}".strip("；")
                if text:
                    samples.append(dict(opportunity=opp.get("name"), customer=opp.get("accountName"),
                                        text=text[:300]))
        out["RC02"] = outcome(
            "RC02", "insufficient",
            reason=f"{len(strategic_pending)} 条战略客户商机待投标；源表没有投标前置条件字段（C02 为空），需读项目进展判断",
            observed=[dict(label="待投标战略客户商机", value=len(strategic_pending)),
                      *[dict(label="项目进展", value=sample) for sample in samples]],
            missing=["投标前置条件检查结果（C02）"])
    out["RC03"] = (outcome("RC03", "triggered", reason="存在 P2 在途超过动态均值 1.5 倍的未签单商机")
                   if "RC03" in candidates else
                   outcome("RC03", "not_triggered", reason="没有 P2 在途超期的未签单商机")
                   if p2_mean_known else
                   outcome("RC03", "insufficient", reason="缺少 P2 阶段周期数据", missing=["P2-01"]))
    gaps = data.get("productTeamGaps") or []
    known = [row for row in gaps if row.get("gapAmount") is not None or row.get("gapEnergy") is not None]
    short = [row for row in known if (row.get("gapAmount") is not None and row["gapAmount"] < 0)
             or (row.get("gapEnergy") is not None and row["gapEnergy"] < 0)]
    gap_fact = fact("C05", "产品部实际销售与目标差距（有缺口团队数）", len(short) if known else None, "个",
                    "C04 产品部累计实际销售 − C03 年度目标，按团队分别计算（本体 C05 SQL）",
                    source="customer PostgreSQL · 本体 C05 指标 SQL")
    observed = [dict(label=f"{row['team'] or '未归属团队'} 差额",
                     value=dict(amount=row.get("gapAmount"), energy=row.get("gapEnergy"),
                                status=row.get("status"))) for row in gaps[:12]]
    if short:
        parts = [f"{row['team'] or '未归属团队'}" + (f" 金额差 {row['gapAmount']:.2f} 亿元" if row.get("gapAmount") is not None and row["gapAmount"] < 0 else "")
                 + (f" 电量差 {row['gapEnergy']:.2f} GWh" if row.get("gapEnergy") is not None and row["gapEnergy"] < 0 else "")
                 for row in short[:6]]
        out["RC04"] = outcome("RC04", "triggered", reason="存在累计实际销售低于年度目标的产品部",
                              description=f"{len(short)} 个产品部累计实际销售低于年度目标：" + "；".join(parts) + "。",
                              evidence=[gap_fact], observed=observed)
    elif known:
        out["RC04"] = outcome("RC04", "not_triggered", reason="各产品部累计实际销售均不低于年度目标",
                              evidence=[gap_fact], observed=observed)
    else:
        status = data.get("productTeamGapStatus") or "unavailable"
        out["RC04"] = outcome("RC04", "insufficient",
                              reason=f"产品部目标与实绩无法配对（C05 查询状态：{status}）",
                              evidence=[gap_fact], observed=observed, missing=["C03 产品部目标", "C04 产品部实绩"])
    ratios = {key: value for key, value in product_pending_ratio.items() if value is not None}
    out["RC05"] = (outcome("RC05", "triggered", reason="某产品类型待签预测占比不低于 20%")
                   if "RC05" in candidates else
                   outcome("RC05", "not_triggered", reason="各产品类型待签占比均低于 20%",
                           observed=[dict(label=f"产品类型 {key} 待签占比", value=value) for key, value in ratios.items()])
                   if ratios else
                   outcome("RC05", "insufficient", reason="缺少产品类型总预测，无法计算待签占比",
                           missing=["R05", "R06"]))
    out["RC06"] = (outcome("RC06", "triggered", reason="重点跟踪占未签单预测低于 70%")
                   if "RC06" in candidates else
                   outcome("RC06", "not_triggered", reason="重点跟踪占未签单预测不低于 70%",
                           observed=[dict(label="C08 重点跟踪占比", value=focus_ratio)])
                   if focus_ratio is not None else
                   outcome("RC06", "insufficient", reason="未签单预测为空，无法计算重点跟踪占比", missing=["C08"]))
    out["RC07"] = (outcome("RC07", "triggered", reason="其余占比不低于 30% 且有需求未确认的 P0 商机")
                   if "RC07" in candidates else
                   outcome("RC07", "not_triggered", reason="其余占比低于 30% 或没有需求未确认的 P0 商机",
                           observed=[dict(label="C09 其余占比", value=rest_ratio)])
                   if rest_ratio is not None else
                   outcome("RC07", "insufficient", reason="未签单预测为空，无法计算其余占比", missing=["C09"]))
    if late_p0:
        # The P0 overrun is established by rule; which sub-step causes it
        # (P0-03~P0-08) has no structured events, so the model decides.
        out["RC08"] = outcome(
            "RC08", "insufficient",
            reason=f"{len(late_p0)} 条商机 P0 周期超过动态均值 1.5 倍；小环节缺少完成事件，卡点需结合进展判断",
            observed=[dict(label="P0 超期商机数", value=len(late_p0)),
                      dict(label="P0 平均周期（天）", value=overall_p0)],
            missing=["P0-05 选择协作团队完成事件", "P0-08 确认客户组织架构完成事件"])
    else:
        out["RC08"] = (outcome("RC08", "not_triggered", reason="没有 P0 阶段超期商机")
                       if opportunities_ok else
                       outcome("RC08", "insufficient", reason="商机数据未取到", missing=["P0-01", "P0-02"]))
    if not no_opportunity:
        out["RC09"] = outcome("RC09", "not_triggered" if source_ok("客户") else "insufficient",
                              reason="没有无商机的战略客户" if source_ok("客户") else "客户数据未取到")
    elif activity_source_ready:
        out["RC09"] = outcome("RC09", "triggered", reason="无商机战略客户近期没有线索、拜访或销售活动")
    else:
        out["RC09"] = outcome("RC09", "insufficient",
                              reason=f"{len(no_opportunity)} 家战略客户无商机；近期线索、拜访与需求调研来源未接入")
    return out


def _program_risk_assessment(candidate):
    """Describe the program's rule outcome without claiming a business verdict.

    The model receives this as the starting point.  A triggered rule is
    supported by the facts the program actually observed; an indeterminate
    rule has no support yet and must not be presented as a business risk.
    """

    status = candidate.get("ruleStatus") or "not_triggered"
    evidence_ids = list(dict.fromkeys(candidate.get("evidenceIds") or []))[:20]
    classification = ("confirmed" if status == "triggered" else
                      "insufficient" if status in {"insufficient", "indeterminate"}
                      else "not_applicable")
    return dict(
        code=candidate.get("code") or "",
        name=candidate.get("name") or "",
        rule=candidate.get("rule") or "",
        condition=candidate.get("condition") or "",
        ruleStatus=status,
        include=status == "triggered",
        classification=classification,
        title=candidate.get("title") or candidate.get("name") or "",
        description=candidate.get("description") or candidate.get("ontologyDescription") or "",
        metricCodes=candidate.get("metricCodes") or [],
        evidenceIds=evidence_ids,
        supportingEvidenceIds=evidence_ids,
        opposingEvidenceIds=[],
        observed=candidate.get("observed") or [],
        missingEvidence=candidate.get("missingEvidence") or [],
    )


def evaluate(data, config=None, measured=None):
    """Apply BR-A*/BR-C* rules to collected facts and return a card result."""
    config = config or load_config()
    strategic_ok, strategic_reason = _strategic_scope(config)
    thresholds = _thresholds(config)
    cycle_config = (config.get("overrides") or {}).get("dynamicCycle") or {}
    cycle_multiplier = _number(cycle_config.get("multiplier"))
    if cycle_multiplier is None:
        raise OpportunityV2Unavailable("本体 BR-Q06 未定义动态周期倍数")
    clean_cycle_sample = _text(cycle_config.get("sample"))
    energy_cfg = (config.get("overrides") or {}).get("electricitySource") or {}
    if _text(energy_cfg.get("mode")) == "amount_div_price":
        energy_field = (f"{_text(energy_cfg.get('amountField')) or 'new_forecast_amt_rmb'}"
                        f" ÷ {_text(energy_cfg.get('priceField')) or 'new_whprice'}")
    else:
        energy_field = _text(energy_cfg.get("field")) or "未定义"
    energy_unit = _text(energy_cfg.get("nativeUnit")) or "未定义"
    measured = _day(measured or data.get("measurementDate")) or date.today()
    target = data.get("targets") or {}
    opps = [dict(item) for item in data.get("opportunities") or [] if isinstance(item, dict)]
    all_opps = [dict(item) for item in data.get("allOpportunities") or [] if isinstance(item, dict)]
    if not all_opps:
        all_opps = [dict(item) for item in opps]
    bids = [dict(item) for item in data.get("bids") or [] if isinstance(item, dict)]
    progress = data.get("progress") or {}
    accounts = [dict(item) for item in data.get("accounts") or [] if isinstance(item, dict)]
    supplement = data.get("supplement") or {}
    aggregates = [dict(item) for item in data.get("opportunityAggregates") or []
                  if isinstance(item, dict)]
    detail_complete = data.get("detailComplete", True)
    all_opps_complete = data.get("allOpportunitiesComplete", True)
    accounts_complete = data.get("accountsComplete", True)
    bids_complete = data.get("bidsComplete", True)
    evidence_facts = {}
    records = []
    evidence_refs = []
    limitations = []
    aggregates_complete = data.get("aggregatesComplete", True)
    aggregate_mode = not detail_complete or not all_opps_complete
    aggregate_ready = aggregate_mode and aggregates_complete and bool(aggregates)

    def aggregate_rows(predicate=None):
        return [row for row in aggregates if predicate is None or predicate(row)]

    def aggregate_measure(field, predicate=None):
        rows = aggregate_rows(predicate)
        if not rows:
            return 0.0
        values = [_number(row.get(field)) for row in rows]
        values = [value for value in values if value is not None]
        return round(sum(values), 6) if values else None

    def aggregate_count(predicate=None):
        rows = aggregate_rows(predicate)
        return sum(int(_number(row.get("count")) or 0) for row in rows)

    def fact(code, label, value, unit="", definition="", source="customer PostgreSQL · ded_public"):
        fid = f"opp-v2:metric:{code}"
        item = dict(id=fid, label=label, value=_round(value, 4) if isinstance(value, (int, float)) else value,
                    unit=unit, definition=definition, source=source,
                    period=data.get("period"), measurementDate=data.get("measurementDate"),
                    definitionVersion=RULES_VERSION)
        evidence_facts[fid] = item
        return fid

    def record(record_id, **fields):
        value = dict(id=record_id, **{key: val for key, val in fields.items() if val not in (None, "")})
        records.append(value)
        evidence_refs.append(dict(id=record_id))
        return record_id

    target_amount = _number(target.get("amount"))
    target_energy = _number(target.get("energy"))
    target_source = "customer PostgreSQL · ded_public"
    if target_amount is None and isinstance(supplement.get("B01"), dict):
        target_amount = _number(supplement["B01"].get("amount"))
        target_source = supplement["B01"].get("source") or "AP 补充"
    if target_energy is None and isinstance(supplement.get("B01"), dict):
        target_energy = _number(supplement["B01"].get("energy"))
        if target_energy is not None:
            target_source = supplement["B01"].get("source") or "AP 补充"
    if aggregate_ready:
        total_amount = aggregate_measure("amount")
        total_energy = aggregate_measure("energy")
    elif aggregate_mode:
        total_amount = None
        total_energy = None
    else:
        total_amount = _sum(opp.get("forecastAmount") for opp in opps)
        total_energy = _sum(opp.get("forecastEnergy") for opp in opps)
    forecast_source = "customer PostgreSQL · ded_public"
    if aggregate_ready:
        forecast_source = "customer PostgreSQL · ded_public · full aggregate"
    if (not aggregate_ready and not opps
            and (data.get("queryStatus") or {}).get("商机预测") == "ok"):
        # A successful query with no approved opportunity is a valid zero, not
        # a missing field that should be replaced by another source.
        total_amount = 0.0
        total_energy = 0.0
    if total_amount is None and isinstance(supplement.get("B02"), dict):
        total_amount = _number(supplement["B02"].get("amount"))
        forecast_source = supplement["B02"].get("source") or "AP 补充"
    if total_energy is None and isinstance(supplement.get("B02"), dict):
        total_energy = _number(supplement["B02"].get("energy"))
        if total_energy is not None:
            forecast_source = supplement["B02"].get("source") or "AP 补充"
    gap_amount = (target_amount - total_amount) if target_amount is not None and total_amount is not None else None
    gap_energy = (target_energy - total_energy) if target_energy is not None and total_energy is not None else None
    gap_rate_amount = _div(gap_amount, target_amount) if gap_amount is not None else None
    gap_rate_energy = _div(gap_energy, target_energy) if gap_energy is not None else None

    confirmed = [opp for opp in opps if opp.get("contract") == "confirmed"]
    unsigned = [opp for opp in opps if opp.get("contract") == "not_confirmed"]
    unknown_contract = [opp for opp in opps if opp.get("contract") == "unknown"]
    unknown_contract_count = (aggregate_count(lambda row: row.get("contract") == "unknown")
                              if aggregate_ready else len(unknown_contract))
    has_opp_data = (bool(opps) or bool(data.get("opportunityAggregates"))
                    or ((data.get("queryStatus") or {}).get("商机预测") == "ok"))
    if aggregate_ready:
        confirmed_amount = aggregate_measure("amount", lambda row: row.get("contract") == "confirmed")
        confirmed_energy = aggregate_measure("energy", lambda row: row.get("contract") == "confirmed")
        unsigned_amount = aggregate_measure("amount", lambda row: row.get("contract") == "not_confirmed")
        unsigned_energy = aggregate_measure("energy", lambda row: row.get("contract") == "not_confirmed")
        unknown_amount = aggregate_measure("amount", lambda row: row.get("contract") == "unknown")
        unknown_energy = aggregate_measure("energy", lambda row: row.get("contract") == "unknown")
    elif aggregate_mode:
        confirmed_amount = confirmed_energy = None
        unsigned_amount = unsigned_energy = None
        unknown_amount = unknown_energy = None
    else:
        confirmed_amount = _sum(opp.get("forecastAmount") for opp in confirmed) if confirmed else (0.0 if has_opp_data else None)
        confirmed_energy = _sum(opp.get("forecastEnergy") for opp in confirmed) if confirmed else (0.0 if has_opp_data else None)
        unsigned_amount = _sum(opp.get("forecastAmount") for opp in unsigned) if unsigned else (0.0 if has_opp_data else None)
        unsigned_energy = _sum(opp.get("forecastEnergy") for opp in unsigned) if unsigned else (0.0 if has_opp_data else None)
        unknown_amount = _sum(opp.get("forecastAmount") for opp in unknown_contract) if unknown_contract else (0.0 if has_opp_data else None)
        unknown_energy = _sum(opp.get("forecastEnergy") for opp in unknown_contract) if unknown_contract else (0.0 if has_opp_data else None)
    # A contract whose state is unknown is neither signed nor explicitly
    # unsigned.  It therefore stays out of both the pending/quarter window and
    # the confirmed signing coverage.
    # R03 / BR-A02 (ontology 2026-11-14): signed coverage = signed forecast ÷
    # total opportunity forecast, unsigned share = unsigned forecast ÷ total
    # forecast; amount and energy separately.  The annual target is not the
    # denominator and its gap is not added.  A total that is empty or 0
    # leaves the ratio NULL.
    unsigned_ratio_amount = _div(unsigned_amount, total_amount)
    unsigned_ratio_energy = _div(unsigned_energy, total_energy)
    sign_progress_amount = _div(confirmed_amount, total_amount)
    sign_progress_energy = _div(confirmed_energy, total_energy)
    year_start = date(measured.year, 1, 1)
    year_end = date(measured.year, 12, 31)
    time_progress = ((measured - year_start).days + 1) / ((year_end - year_start).days + 1)
    lag_amount = (time_progress - sign_progress_amount) * 100 if sign_progress_amount is not None else None
    lag_energy = (time_progress - sign_progress_energy) * 100 if sign_progress_energy is not None else None
    quarter = (measured.month - 1) // 3 + 1
    quarter_window = _number((thresholds.get("quarterWindows") or {}).get(str(quarter)))

    # R04: 战略 + 重点 unsigned opportunities of customers in the 储能客户名单 (BR-Q04).
    focus = [opp for opp in unsigned if opp.get("tier") in {"strategic", "priority"} and _in_storage(opp)]
    if not strategic_ok:
        # R04 is "战略 + 重点"; without an authoritative strategic list the
        # value would silently collapse to priority-only, so it stays unknown.
        focus_amount = focus_energy = None
        focus_count = 0
        focus_has_strategic = False
    elif aggregate_ready:
        focus_predicate = lambda row: (row.get("contract") == "not_confirmed"
                                       and row.get("tier") in {"strategic", "priority"}
                                       and _in_storage(row))
        focus_amount = aggregate_measure("amount", focus_predicate)
        focus_energy = aggregate_measure("energy", focus_predicate)
        focus_count = aggregate_count(focus_predicate)
        focus_has_strategic = bool(aggregate_rows(
            lambda row: row.get("contract") == "not_confirmed"
            and row.get("tier") == "strategic" and _in_storage(row)))
    elif aggregate_mode:
        focus_amount = focus_energy = None
        focus_count = 0
        focus_has_strategic = False
    else:
        focus_amount = _sum(opp.get("forecastAmount") for opp in focus) if focus else 0.0
        focus_energy = _sum(opp.get("forecastEnergy") for opp in focus) if focus else 0.0
        focus_count = len({opp.get("id") for opp in focus if opp.get("id")})
        focus_has_strategic = any(opp.get("tier") == "strategic" for opp in focus)

    products = {}
    for key in ("1", "2", "unknown"):
        subset = [opp for opp in unsigned if opp.get("productType") == key]
        total_subset = [opp for opp in opps if opp.get("productType") == key]
        if aggregate_ready:
            pending_predicate = lambda row: (row.get("contract") == "not_confirmed"
                                             and row.get("productType") == key)
            confirmed_predicate = lambda row: (row.get("contract") == "confirmed"
                                               and row.get("productType") == key)
            total_predicate = lambda row: row.get("productType") == key
            pending_amount = aggregate_measure("amount", pending_predicate)
            pending_energy = aggregate_measure("energy", pending_predicate)
            confirmed_product_amount = aggregate_measure("amount", confirmed_predicate)
            confirmed_product_energy = aggregate_measure("energy", confirmed_predicate)
            product_total_amount = aggregate_measure("amount", total_predicate)
            product_total_energy = aggregate_measure("energy", total_predicate)
            pending_count = aggregate_count(pending_predicate)
        elif aggregate_mode:
            pending_amount = pending_energy = None
            confirmed_product_amount = confirmed_product_energy = None
            product_total_amount = product_total_energy = None
            pending_count = 0
        else:
            pending_amount = _sum(opp.get("forecastAmount") for opp in subset)
            pending_energy = _sum(opp.get("forecastEnergy") for opp in subset)
            confirmed_subset = [opp for opp in confirmed if opp.get("productType") == key]
            confirmed_product_amount = (_sum(opp.get("forecastAmount") for opp in confirmed_subset)
                                        if confirmed_subset else (0.0 if has_opp_data else None))
            confirmed_product_energy = (_sum(opp.get("forecastEnergy") for opp in confirmed_subset)
                                        if confirmed_subset else (0.0 if has_opp_data else None))
            product_total_amount = _sum(opp.get("forecastAmount") for opp in total_subset)
            product_total_energy = _sum(opp.get("forecastEnergy") for opp in total_subset)
            pending_count = len({opp.get("id") for opp in subset if opp.get("id")})
        product_target_amount = _number((target.get("byProduct") or {}).get(key, {}).get("amount"))
        product_target_energy = _number((target.get("byProduct") or {}).get(key, {}).get("energy"))
        product_gap_amount = (product_target_amount - product_total_amount
                              if product_target_amount is not None and product_total_amount is not None else None)
        product_gap_energy = (product_target_energy - product_total_energy
                              if product_target_energy is not None and product_total_energy is not None else None)
        # R05 / R06 condition ② uses the same product's signed forecast ÷ its
        # total forecast; condition ① (forecast below target) keeps the target.
        product_sign_progress_amount = _div(confirmed_product_amount, product_total_amount)
        product_sign_progress_energy = _div(confirmed_product_energy, product_total_energy)
        products[key] = dict(
            pending=subset,
            pending_count=pending_count,
            pending_amount=pending_amount,
            pending_energy=pending_energy,
            confirmed_amount=confirmed_product_amount,
            confirmed_energy=confirmed_product_energy,
            total_amount=product_total_amount,
            total_energy=product_total_energy,
            target_amount=product_target_amount,
            target_energy=product_target_energy,
            gap_amount=product_gap_amount,
            gap_energy=product_gap_energy,
            sign_progress_amount=product_sign_progress_amount,
            sign_progress_energy=product_sign_progress_energy,
            lag_amount=((time_progress - product_sign_progress_amount) * 100
                        if product_sign_progress_amount is not None else None),
            lag_energy=((time_progress - product_sign_progress_energy) * 100
                        if product_sign_progress_energy is not None else None),
        )

    # R08 (ontology customer_gaps): target and forecast are paired per customer
    # and product type (电芯 / PACK / 其他).  A side that is missing leaves that
    # pair's gap empty; it is never read as zero.  BR-A06 needs an opportunity
    # forecast for the pair and a gap > 0.
    forecast_pairs = {}
    if aggregate_ready:
        forecast_source_rows = [dict(accountId=row.get("accountId"), productType=row.get("productType"),
                                     amount=row.get("amount"), energy=row.get("energy"),
                                     accountName=row.get("accountName"), tier=row.get("tier"),
                                     count=int(row.get("count") or 0)) for row in aggregates]
    elif aggregate_mode:
        forecast_source_rows = []
    else:
        forecast_source_rows = [dict(accountId=opp.get("accountId"), productType=opp.get("productType"),
                                     amount=opp.get("forecastAmount"), energy=opp.get("forecastEnergy"),
                                     accountName=opp.get("accountName"), tier=opp.get("tier"), count=1)
                                for opp in opps if (opp.get("monthRows") or opp.get("forecastAmount") is not None
                                                    or opp.get("forecastEnergy") is not None)]
    for row in forecast_source_rows:
        account_id = row.get("accountId") or ""
        if not account_id:
            continue
        pair = forecast_pairs.setdefault((account_id, row.get("productType") or "unknown"), dict(
            amount=None, energy=None, count=0, accountName="", tier="unknown"))
        if _number(row.get("amount")) is not None:
            pair["amount"] = (pair["amount"] or 0.0) + _number(row.get("amount"))
        if _number(row.get("energy")) is not None:
            pair["energy"] = (pair["energy"] or 0.0) + _number(row.get("energy"))
        pair["count"] += row.get("count") or 0
        pair["accountName"] = pair["accountName"] or row.get("accountName") or ""
        if pair["tier"] == "unknown":
            pair["tier"] = row.get("tier") or "unknown"
    target_pairs = {(item.get("accountId"), item.get("productType") or "unknown"): item
                    for item in (target.get("byAccountProduct") or {}).values()
                    if isinstance(item, dict) and item.get("accountId")}
    customer_gaps = []
    for key in sorted(set(target_pairs) & set(forecast_pairs)):
        goal, forecast = target_pairs[key], forecast_pairs[key]
        if not _in_storage(goal):
            continue  # R08 covers the 储能客户名单 only (BR-Q04)
        amount_gap = (_number(goal.get("amount")) - forecast["amount"]
                      if _number(goal.get("amount")) is not None and forecast["amount"] is not None else None)
        energy_gap = (_number(goal.get("energy")) - forecast["energy"]
                      if _number(goal.get("energy")) is not None and forecast["energy"] is not None else None)
        if (amount_gap or 0) > 0 or (energy_gap or 0) > 0:
            account_id, product = key
            customer_gaps.append(dict(accountId=account_id, productType=product,
                                      productName=_product_name(product, config),
                                      accountName=forecast["accountName"], tier=forecast["tier"],
                                      amount=amount_gap, energy=energy_gap, count=forecast["count"]))
    gap_accounts = {gap["accountId"] for gap in customer_gaps}

    # Bid names are matched exactly after trimming.  Duplicate names are
    # ambiguous and never become "not bidding".
    bid_names = defaultdict(list)
    for bid in bids:
        name = _text(bid.get("name"))
        if name:
            bid_names[name].append(bid)
    ambiguous_bid_names = {name for name, values in bid_names.items() if len(values) > 1}
    all_opp_by_id = {opp.get("id"): opp for opp in all_opps if opp.get("id")}
    for opp in all_opps + opps:
        candidates = bid_names.get(_text(opp.get("name")), []) if all_opps_complete else []
        if not all_opps_complete:
            opp["bidding"] = "unknown"
            opp["bidId"] = ""
        elif len(candidates) == 1:
            opp["bidding"] = "yes"
            opp["bidId"] = candidates[0].get("id")
        elif len(candidates) > 1:
            opp["bidding"] = "ambiguous"
            opp["bidId"] = ""
        else:
            opp["bidding"] = "no"
            opp["bidId"] = ""

    strategic_accounts = {account["id"]: account for account in accounts if account.get("tier") == "strategic"}
    active_by_account = defaultdict(list)
    all_by_account = defaultdict(list)
    for opp in all_opps:
        account_id = opp.get("accountId") or ""
        all_by_account[account_id].append(opp)
        if opp.get("status") == "0":
            active_by_account[account_id].append(opp)
    complete_opportunity_scope = all_opps_complete and accounts_complete

    # R09 (ontology customer_coverage): a strategic customer counts when no
    # opportunity at all is linked to it, whatever the customer's or the
    # opportunities' creation year, state or approval.  The customer query
    # carries that count; older inputs without it fall back to the fetched
    # opportunity list.
    def linked_count(account_id, account):
        if "opportunityCount" in account:
            return int(account.get("opportunityCount") or 0)
        return len(all_by_account.get(account_id) or [])

    no_opportunity = [account for account_id, account in strategic_accounts.items()
                      if accounts_complete and linked_count(account_id, account) == 0]
    no_bidding = []
    for account_id, account in strategic_accounts.items():
        if not complete_opportunity_scope:
            break
        # A historical closed/won opportunity must not hide a currently active
        # customer that has no bid in this period.
        values = active_by_account.get(account_id) or []
        if values and all(opp.get("bidding") == "no" for opp in values):
            no_bidding.append(account)

    for opp in opps:
        source = all_opp_by_id.get(opp.get("id"))
        if source:
            opp["bidding"] = source.get("bidding", "unknown")
            opp["bidId"] = source.get("bidId", "")

    valid_bids = []
    for bid in bids:
        if not bids_complete:
            break
        input_day = _day(bid.get("inputAt"))
        winner_day = _day(bid.get("winnerAt"))
        if not input_day or input_day > measured or (winner_day and winner_day > measured):
            continue
        valid_bids.append(bid)
    in_progress_bids = [bid for bid in valid_bids if bid.get("inProgress")]
    bid_product = {opp.get("bidId"): opp.get("productType") for opp in all_opps
                   if opp.get("bidId")}
    bid_cycles_by_product = defaultdict(list)
    for bid in valid_bids:
        if bid.get("cycleDays") is not None:
            bid_cycles_by_product[bid_product.get(bid.get("id"), "unknown")].append(bid["cycleDays"])
    bid_average_by_product = ({key: _avg(values) for key, values in bid_cycles_by_product.items()}
                              if all_opps_complete else {})
    bid_average = _avg([bid.get("cycleDays") for bid in valid_bids if bid.get("cycleDays") is not None])

    # Dynamic stage averages are per product type.  Samples exclude missing or
    # inverted entering times and record their coverage separately.
    def entered_this_year(opp, stage):
        start = _day(opp.get("createdAt")) if stage == "P0" else _day(opp.get("stage2End"))
        return bool(start and start.year == measured.year and start <= measured)

    # BR-Q06: with completedOnly the mean counts only stages with a real start
    # and end; an unfinished stage keeps its elapsed time (p0Cycle / p2Cycle)
    # for the overdue comparison but is never averaged in.
    completed_only = bool(cycle_config.get("completedOnly"))

    def mean_sample(opp, stage, elapsed):
        if not completed_only:
            return elapsed
        if stage == "P0":
            return _stage_completed(_day(opp.get("createdAt")), _day(opp.get("stage1End")), measured)
        return _stage_completed(_day(opp.get("stage2End")), _day(opp.get("stage3End")), measured)

    stage_samples = defaultdict(lambda: defaultdict(list))
    overall_samples = dict(P0=[], P2=[])
    for opp in opps:
        p0 = _p0_cycle(opp, measured) if detail_complete else None
        p2 = _p2_cycle(opp, measured) if detail_complete else None
        opp["p0Cycle"] = p0
        opp["p2Cycle"] = p2
        for stage, elapsed in (("P0", p0), ("P2", p2)):
            if not detail_complete or elapsed is None or not entered_this_year(opp, stage):
                continue
            sample = mean_sample(opp, stage, elapsed)
            if sample is not None:
                stage_samples[opp.get("productType", "unknown")][stage].append(sample)
                overall_samples[stage].append(sample)
    stage_average = {product: {stage: _avg(values) for stage, values in groups.items()}
                     for product, groups in stage_samples.items()}
    overall_p0 = _avg(overall_samples["P0"]) if detail_complete else None
    overall_p2 = _avg(overall_samples["P2"]) if detail_complete else None
    cycle_basis = "已结束样本" if completed_only else "含在途样本"

    def multiplier(product, stage):
        value = stage_average.get(product, {}).get(stage)
        return value if value is not None else (overall_p0 if stage == "P0" else overall_p2)

    late_p0 = []
    late_p2 = []
    if detail_complete:
        for opp in opps:
            average = multiplier(opp.get("productType", "unknown"), "P0")
            if (entered_this_year(opp, "P0") and average and opp.get("p0Cycle") is not None
                    and opp["p0Cycle"] > average * cycle_multiplier):
                late_p0.append(opp)
            average2 = multiplier(opp.get("productType", "unknown"), "P2")
            if (entered_this_year(opp, "P2") and average2 and opp.get("p2Cycle") is not None
                    and opp["p2Cycle"] > average2 * cycle_multiplier):
                late_p2.append(opp)

    # Facts: stable ids, one source, one period and one unit per measure.
    f_b01_a = fact("B01-AMOUNT", "年度销售目标（金额）", target_amount, "亿元",
                   "同年度、组织和产品范围的销售额目标", source=target_source)
    f_b01_e = fact("B01-ENERGY", "年度销售目标（电量）", target_energy, "GWh",
                   "同年度、组织和产品范围的电量目标", source=target_source)
    f_b02_a = fact("B02-AMOUNT", "商机总预测（金额）", total_amount, "亿元",
                   "BR-Q01：所选年度同商机同月取最新一版，只用预测金额 new_forecast_amt_rmb，"
                   "不混入已历月份实绩；不限定审核或业务状态", source=forecast_source)
    f_b02_e = fact("B02-ENERGY", "商机总预测（电量）", total_energy, "GWh",
                   "预测金额 ÷ new_whprice（元/Wh）÷ 10^9；本体 BR-Q01，new_forcastpower 实库为空",
                   source=forecast_source)
    gap_source = target_source if target_source == forecast_source else f"derived（{target_source} / {forecast_source}）"
    f_r01_a = fact("R01-AMOUNT", "商机预测缺口（金额）", gap_amount, "亿元", "B01 − B02，金额单独计算", source=gap_source)
    f_r01_e = fact("R01-ENERGY", "商机预测缺口（电量）", gap_energy, "GWh", "B01 − B02，电量单独计算", source=gap_source)
    f_gap_rate_a = fact("R01-RATE-AMOUNT", "商机预测缺口率（金额）", gap_rate_amount * 100 if gap_rate_amount is not None else None, "%")
    f_gap_rate_e = fact("R01-RATE-ENERGY", "商机预测缺口率（电量）", gap_rate_energy * 100 if gap_rate_energy is not None else None, "%")
    f_r02_a = fact("R02-AMOUNT", "明确未签单商机预测（金额）", unsigned_amount, "亿元", "BR-Q02：未关联到订单")
    f_r02_e = fact("R02-ENERGY", "明确未签单商机预测（电量）", unsigned_energy, "GWh", "BR-Q02：未关联到订单")
    f_r02_unknown_a = fact("R02-UNKNOWN-AMOUNT", "签单状态未知商机预测（金额）", unknown_amount, "亿元", "签单状态无法判定")
    f_r02_unknown_e = fact("R02-UNKNOWN-ENERGY", "签单状态未知商机预测（电量）", unknown_energy, "GWh", "签单状态无法判定")
    f_r02_confirmed_a = fact("R02-CONFIRMED-AMOUNT", "已签单商机预测（金额）", confirmed_amount, "亿元", "BR-Q02：已关联至少 1 张订单")
    f_r02_confirmed_e = fact("R02-CONFIRMED-ENERGY", "已签单商机预测（电量）", confirmed_energy, "GWh", "BR-Q02：已关联至少 1 张订单")
    f_r03 = fact("R03-LAG", "已签单覆盖率落后时间进度（金额）", lag_amount, "百分点",
                 "已签单覆盖率 = 已签单商机预测金额 ÷ 商机预测总金额；总预测为空或为 0 时不计算")
    f_r03_e = fact("R03-LAG-ENERGY", "已签单覆盖率落后时间进度（电量）", lag_energy, "百分点",
                   "已签单覆盖率 = 已签单商机预测电量 ÷ 商机预测总电量；总预测为空或为 0 时不计算")
    storage_on = bool(((config.get("overrides") or {}).get("storageCustomerScope") or {}).get("enabled"))
    storage_note = "储能客户名单内（BR-Q04）；" if storage_on else ""
    f_r04_count = fact("R04-COUNT", "重点跟踪未签单商机数", focus_count, "条",
                       storage_note + "战略、重点客户的未签单商机，按商机 ID 去重")
    f_r04_a = fact("R04-AMOUNT", "重点跟踪未签单预测（金额）", focus_amount, "亿元")
    f_r04_e = fact("R04-ENERGY", "重点跟踪未签单预测（电量）", focus_energy, "GWh")
    f_r05_a = fact("R05-AMOUNT", "电芯类未签单预测（金额）", products["1"]["pending_amount"], "亿元")
    f_r05_e = fact("R05-ENERGY", "电芯类未签单预测（电量）", products["1"]["pending_energy"], "GWh")
    f_r06_a = fact("R06-AMOUNT", "PACK 类未签单预测（金额）", products["2"]["pending_amount"], "亿元")
    f_r06_e = fact("R06-ENERGY", "PACK 类未签单预测（电量）", products["2"]["pending_energy"], "GWh")
    f_r08 = fact("R08", "客户预测缺口客户数", len(gap_accounts), "家",
                 storage_note + "按客户＋产品类型分别计算目标 − 商机预测；任一侧缺值不计缺口；金额或电量缺口大于 0")
    supplement_r09 = (_number((supplement.get("R09") or {}).get("count"))
                      if strategic_ok and isinstance(supplement.get("R09"), dict) else None)
    if strategic_ok:
        no_opportunity_count = len(no_opportunity)
        r09_source = "customer PostgreSQL · ded_public"
        if not accounts and supplement_r09 is not None:
            no_opportunity_count = max(0, int(supplement_r09))
            r09_source = supplement["R09"].get("source") or "AP 补充"
    else:
        no_opportunity_count = None
        r09_source = "本体未提供战略客户名单"
    f_r09 = fact("R09", "无商机战略客户数", no_opportunity_count, "家",
                 storage_note + "战略客户中关联商机数为 0 的客户（客户.accountid = 商机.parentaccountid）；"
                 "不按创建年份、审批或业务状态筛选", source=r09_source)
    f_r10 = fact("R10", "有商机未投标战略客户数",
                 len(no_bidding) if strategic_ok else None, "家",
                 "全部商机均未进入投标；同名歧义不判未投标" if strategic_ok
                 else "本体未提供战略客户名单，未执行逐客户判断")
    f_r11 = fact("R11", "投标中商机数", len(in_progress_bids), "条", "已录入且尚未公布中标人")
    f_s03 = fact("S03", "投标平均周期", bid_average, "天", "中标公布时间或测量日 − 录入时间；全部有效投标")
    f_s03_p1 = fact("S03-P1", "电芯类投标平均周期", bid_average_by_product.get("1"), "天", "按关联商机产品类型拆分")
    f_s03_p2 = fact("S03-P2", "PACK 类投标平均周期", bid_average_by_product.get("2"), "天", "按关联商机产品类型拆分")
    f_p0 = fact("P0-01", "商机获取阶段平均周期", overall_p0, "天",
                ("创建至阶段一结束；仅统计完整有效起止的已结束样本，在途不计入均值；按电芯/PACK 分别计算"
                 if completed_only else "创建至阶段一结束或测量日；按电芯/PACK 分别计算"))
    f_p2 = fact("P2-01", "方案推动阶段平均周期", overall_p2, "天",
                ("阶段三结束 − 阶段二结束；仅统计完整有效起止的已结束样本，在途不计入均值；按电芯/PACK 分别计算"
                 if completed_only else "阶段三结束或测量日 − 阶段二结束；按电芯/PACK 分别计算"))
    f_rk10 = fact("P0-02", "商机获取阶段超期商机数", len(late_p0), "条", "单笔周期严格大于同阶段同产品平均周期 × 1.5")
    f_bid_amb = fact("BID-AMBIGUOUS", "投标同名歧义项目数", len(ambiguous_bid_names), "个", "同名多条投标记录；不据此判断未投标")

    risks = []
    top_opps = lambda values, limit=8: [record(
        f"opp-v2:opp:{opp.get('id')}", customer=opp.get("accountName"), department=opp.get("department"),
        product=opp.get("productName"), status=f"{opp.get('stageName')}·{'已签单' if opp.get('contract') == 'confirmed' else '未签单' if opp.get('contract') == 'not_confirmed' else '签单状态未知'}",
        amount=opp.get("forecastAmount"), quantity=opp.get("forecastEnergy"), unit="亿元/GWh",
        value=opp.get("name"), name=opp.get("name"), evidence=opp.get("id"),
    ) for opp in values[:limit] if opp.get("id")]

    # RK01
    if (gap_amount is not None and gap_amount > 0) or (gap_energy is not None and gap_energy > 0):
        rate = max([value for value in (gap_rate_amount, gap_rate_energy) if value is not None] or [0])
        level = _level_for_gap(rate, thresholds)
        parts = []
        if gap_amount is not None and gap_amount > 0:
            parts.append(f"金额缺口 {gap_amount:.2f} 亿元（目标 {target_amount:.2f} 亿元、预测 {total_amount:.2f} 亿元）。")
        if gap_energy is not None and gap_energy > 0:
            parts.append(f"电量缺口 {gap_energy:.2f} GWh（目标 {target_energy:.2f} GWh、预测 {total_energy:.2f} GWh）。")
        evidence = [f_b01_a, f_b01_e, f_b02_a, f_b02_e, f_r01_a, f_r01_e, f_gap_rate_a, f_gap_rate_e]
        name = _risk_name(config, "RK01", "商机预测覆盖不足")
        risks.append(_risk("RK01", name, level, f"RK01 {name}",
                           "".join(parts), ["RK01", "R01", "B01", "B02"], evidence,
                           dict(amount=gap_amount, energy=gap_energy, count=None), []))

    # RK02
    quarterly = quarter_window is not None and (
        (unsigned_ratio_amount is not None and unsigned_ratio_amount > quarter_window)
        or (unsigned_ratio_energy is not None and unsigned_ratio_energy > quarter_window)
    )
    if (lag_amount is not None and lag_amount > 0) or (lag_energy is not None and lag_energy > 0) or quarterly:
        lag = max([value for value in (lag_amount, lag_energy) if value is not None] or [0])
        level = ("极高" if lag >= thresholds["signLagExtremePoints"] else
                 "高" if lag >= thresholds["signLagHighPoints"] else "中")
        parts = []
        if lag_amount is not None:
            parts.append(f"金额口径已签单覆盖率 {sign_progress_amount * 100:.1f}%、时间进度 {time_progress * 100:.1f}%，落后 {lag_amount:.1f} 个百分点。")
        if lag_energy is not None:
            parts.append(f"电量口径已签单覆盖率 {sign_progress_energy * 100:.1f}%，落后 {lag_energy:.1f} 个百分点。")
        if quarterly:
            parts.append(f"第 {quarter} 季度未签单商机预测占比超过 {quarter_window * 100:.0f}% 窗口阈值。")
        evidence = [f_r03, f_r03_e, f_r02_a, f_r02_e, f_r02_unknown_a, f_r02_unknown_e,
                    f_b02_a, f_b02_e]
        name = _risk_name(config, "RK02", "签单进度滞后")
        risks.append(_risk("RK02", name, level, f"RK02 {name}（已签单覆盖率口径）",
                           "".join(parts), ["RK02", "R03", "R02", "B02"], evidence,
                           dict(amount=unsigned_amount, energy=unsigned_energy, count=None), []))

    # RK03
    if ((gap_amount is not None and gap_amount > 0) or (gap_energy is not None and gap_energy > 0)) and focus_count and ((focus_amount or 0) > 0 or (focus_energy or 0) > 0):
        level = "高" if focus_has_strategic else "中"
        parts = [f"战略及重点客户未签单商机 {focus_count} 条"]
        if focus_amount:
            parts.append(f"涉及预测金额 {focus_amount:.2f} 亿元")
        if focus_energy:
            parts.append(f"涉及预测电量 {focus_energy:.2f} GWh")
        evidence = [f_r04_count, f_r04_a, f_r04_e, f_r01_a, f_r01_e]
        name = _risk_name(config, "RK03", "战略及重点客户存在缺口")
        risks.append(_risk("RK03", name, level, f"RK03 {name}",
                           "，".join(parts) + "；尚未关联订单。", ["RK03", "R04", "R01"], evidence,
                           dict(amount=focus_amount, energy=focus_energy, count=focus_count), []))

    # RK04/RK05
    for code, key in (("RK04", "1"), ("RK05", "2")):
        bucket = products[key]
        pending_amount = bucket["pending_amount"] or 0
        pending_energy = bucket["pending_energy"] or 0
        if pending_amount <= 0 and pending_energy <= 0:
            continue
        target_a = bucket.get("target_amount")
        target_e = bucket.get("target_energy")
        under = ((target_a is not None and bucket.get("total_amount") is not None and bucket["total_amount"] < target_a)
                 or (target_e is not None and bucket.get("total_energy") is not None and bucket["total_energy"] < target_e))
        lagged = ((bucket.get("lag_amount") is not None and bucket["lag_amount"] > 0)
                  or (bucket.get("lag_energy") is not None and bucket["lag_energy"] > 0))
        if not under and not lagged:
            continue
        level = ("高" if pending_amount >= thresholds["productRiskAmountHigh"] else
                 "中" if pending_amount >= thresholds["productRiskAmountMedium"] else "低")
        parts = []
        if pending_amount:
            parts.append(f"未签单预测金额 {pending_amount:.2f} 亿元")
        if pending_energy:
            parts.append(f"未签单预测电量 {pending_energy:.2f} GWh")
        if under:
            parts.append("该类总预测低于同口径目标")
        product_lags = [value for value in (bucket.get("lag_amount"), bucket.get("lag_energy"))
                        if value is not None]
        if lagged and product_lags:
            parts.append(f"该类已签单覆盖率落后时间进度 {max(product_lags):.1f} 个百分点")
        evidence = [f_r05_a if key == "1" else f_r06_a, f_r05_e if key == "1" else f_r06_e]
        name = _risk_name(config, code, "电芯类签单存在缺口" if key == "1" else "PACK类签单存在缺口")
        risks.append(_risk(code, name, level, f"{code} {name}",
                           "，".join(parts) + "；按 BR-Q02 订单关联口径判断。",
                           [code, "R05" if key == "1" else "R06", "B01", "B02"], evidence,
                           dict(amount=pending_amount, energy=pending_energy, count=bucket["pending_count"]), []))

    # RK06
    if customer_gaps:
        level = "高" if any(gap.get("tier") == "strategic" for gap in customer_gaps) else "中"
        amount_total = _sum(gap.get("amount") for gap in customer_gaps)
        energy_total = _sum(gap.get("energy") for gap in customer_gaps)
        parts = [f"{len(gap_accounts)} 家客户（{len(customer_gaps)} 个客户×产品组合）的目标高于商机预测"]
        if amount_total:
            parts.append(f"金额缺口合计 {amount_total:.2f} 亿元")
        if energy_total:
            parts.append(f"电量缺口合计 {energy_total:.2f} GWh")
        evidence = [f_r08]
        for gap in customer_gaps[:8]:
            account_id = gap.get("accountId")
            if account_id:
                evidence.append(record(f"opp-v2:account:{account_id}:{gap.get('productType')}",
                                       customer=gap.get("accountName"), product=gap.get("productName"),
                                       amount=_round(gap.get("amount"), 4),
                                       quantity=_round(gap.get("energy"), 4),
                                       unit="亿元/GWh", value=account_id, name=gap.get("accountName")))
        name = _risk_name(config, "RK06", "客户预测不足存在缺口")
        risks.append(_risk("RK06", name, level, f"RK06 {name}",
                           "，".join(parts) + "。", ["RK06", "R08"], evidence,
                           dict(amount=_round(amount_total, 4), energy=_round(energy_total, 4),
                                count=len(gap_accounts)), []))

    # RK07
    if no_opportunity or (not accounts and no_opportunity_count):
        evidence = [f_r09]
        for account in no_opportunity[:10]:
            evidence.append(record(f"opp-v2:account:{account.get('id')}", customer=account.get("name"),
                                   status="无关联商机",
                                   value=account.get("id"), name=account.get("name")))
        description = (f"战略客户中有 {no_opportunity_count} 家没有任何关联商机。"
                       if accounts else f"AP 补充口径显示有 {no_opportunity_count} 家无商机战略客户；客户明细未取得，不能归因。")
        name = _risk_name(config, "RK07", "战略客户签单存在缺口，且较多待突破（无商机）")
        risks.append(_risk("RK07", name, "高", f"RK07 {name}",
                           description, ["RK07", "R09"], evidence, dict(count=no_opportunity_count), []))

    # RK08
    if no_bidding:
        affected = [opp for account in no_bidding for opp in all_by_account.get(account.get("id"), [])]
        lagging = [opp for opp in affected if opp in late_p0 or opp in late_p2]
        level = "极高" if lagging else "高"
        evidence = [f_r10, f_bid_amb]
        for account in no_bidding[:8]:
            evidence.append(record(f"opp-v2:account:{account.get('id')}", customer=account.get("name"),
                                   status="有商机、全部未进入投标", value=account.get("id"), name=account.get("name")))
        risks.append(_risk("RK08", "战略客户有商机未投标", level, "RK08 战略客户有商机未投标",
                           f"{len(no_bidding)} 家战略客户有商机但全部未进入投标" + (f"；其中 {len(lagging)} 条商机推进超期" if lagging else "") + f"；同名歧义 {len(ambiguous_bid_names)} 个，未判为未投标。",
                           ["RK08", "R10", "D_IS_BIDDING"], evidence,
                           dict(count=len(no_bidding), amount=_sum(opp.get("forecastAmount") for opp in affected),
                                energy=_sum(opp.get("forecastEnergy") for opp in affected)), []))

    # RK09
    late_bids = []
    if bid_average:
        for bid in in_progress_bids:
            average = bid_average_by_product.get(bid_product.get(bid.get("id"), "unknown")) or bid_average
            if bid.get("cycleDays") is not None and bid["cycleDays"] > average * cycle_multiplier:
                late_bids.append(bid)
    if late_bids:
        impacted = []
        for bid in late_bids:
            opp = next((item for item in opps if item.get("bidId") == bid.get("id")), None)
            if opp:
                impacted.append(opp)
        level = "高" if any(opp.get("tier") in {"strategic", "priority"} for opp in impacted) else "中"
        evidence = [f_s03, f_s03_p1, f_s03_p2, f_r11]
        for bid in late_bids[:8]:
            evidence.append(record(f"opp-v2:bid:{bid.get('id')}", name=bid.get("name"),
                                   status="投标中", value=bid.get("cycleDays"), unit="天",
                                   evidence=bid.get("id")))
        risks.append(_risk("RK09", "投标中商机超期", level, "RK09 投标中商机超期",
                           f"投标中 {len(in_progress_bids)} 项，按关联产品类型均值比较后，超过 1.5 倍的 {len(late_bids)} 项。",
                           ["RK09", "R11", "S03"], evidence,
                           dict(count=len(late_bids), amount=_sum(opp.get("forecastAmount") for opp in impacted),
                                energy=_sum(opp.get("forecastEnergy") for opp in impacted)), []))

    # RK10
    if late_p0:
        affected_amount = _sum(opp.get("forecastAmount") for opp in late_p0)
        affected_energy = _sum(opp.get("forecastEnergy") for opp in late_p0)
        level = "高" if (affected_amount or 0) >= 10 else "中"
        evidence = [f_p0, f_rk10]
        evidence.extend(top_opps(late_p0))
        name = _risk_name(config, "RK10", "商机获取阶段超期较多，影响签单")
        risks.append(_risk("RK10", name, level, f"RK10 {name}",
                           f"{len(late_p0)} 条商机单笔周期超过同阶段同产品{cycle_basis}平均周期 1.5 倍；"
                           f"平均周期 {overall_p0:.1f} 天。",
                           ["RK10", "P0-01", "P0-02"], evidence,
                           dict(count=len(late_p0), amount=affected_amount, energy=affected_energy),
                           [opp.get("id") for opp in late_p0]))

    # De-duplicate by code and sort by level, then normalised impact and code.
    # Money and energy remain separate fields; this is presentation order only.
    unique = {risk["code"]: risk for risk in risks}

    def impact_ratio(risk):
        # Compare ratios, never raw yuan with MWh.  This keeps a large energy
        # risk from outranking a high-value money risk merely because its unit
        # happens to produce a larger number.
        impact = risk.get("impact") or {}
        ratios = []
        amount = _number(impact.get("amount"))
        energy = _number(impact.get("energy"))
        count = _number(impact.get("count"))
        if amount is not None and target_amount:
            ratios.append(abs(amount) / target_amount)
        if energy is not None and target_energy:
            ratios.append(abs(energy) / target_energy)
        if count is not None:
            ratios.append(abs(count) / 100.0)
        return max(ratios or [0.0])

    configured_risks = set(config.get("risks") or {})
    risks = sorted((risk for risk in unique.values() if risk["code"] in configured_risks),
                   key=lambda item: (item["levelRank"], -round(impact_ratio(item), 6), item["code"]))
    for risk in risks:
        risk["id"] = f"opp-v2:risk:{risk['code']}"
        risk["kind"] = "risk_fact"
        risk["impactScore"] = round(impact_ratio(risk), 6)

    # Every ontology risk is sent to the model, including rules the program
    # computed as not met.  The program supplies the rule, observed facts and
    # missing inputs; it does not hide candidates before the model weighs them.
    triggered_by_code = {risk["code"]: risk for risk in risks}
    source_status = data.get("queryStatus") or {}

    def source_ok(label):
        # A present status map is authoritative.  Older callers/tests without
        # one never get a silent "not applicable" verdict.
        return bool(source_status) and source_status.get(label) == "ok"

    strategic_present = any(account.get("tier") == "strategic" for account in accounts)
    strategic_scope = strategic_present or bool(no_opportunity_count) or bool(no_bidding)
    applicable = {
        "RK04": bool(products["1"].get("pending_count")
                     or products["1"].get("target_amount") is not None
                     or products["1"].get("target_energy") is not None),
        "RK05": bool(products["2"].get("pending_count")
                     or products["2"].get("target_amount") is not None
                     or products["2"].get("target_energy") is not None),
        "RK06": bool(target.get("byAccount")),
        "RK07": strategic_scope or not source_ok("客户"),
        "RK08": strategic_scope or not source_ok("客户"),
        "RK09": bool(valid_bids) or not source_ok("投标"),
        "RK10": bool(opps) or not source_ok("商机预测"),
    }
    risk_candidates = []
    for code, spec in (config.get("risks") or {}).items():
        triggered = triggered_by_code.get(code)
        required_codes = list(_RISK_FACT_CODES.get(code, ()))
        required = [evidence_facts.get(f"opp-v2:metric:{fact_code}")
                    for fact_code in required_codes]
        fact_items = [item for item in required if item]
        # Missing facts include a required fact that was never produced as well
        # as a fact whose value is null.  Neither is a genuine zero.
        missing = [fact_code for fact_code, item in zip(required_codes, required)
                   if not item or item.get("value") is None]
        # A rule whose required fact is empty did not fail; it could not be
        # settled from the available data.  Only rules with all required facts
        # present can be reported as a genuine not_triggered result.
        rule_status = ("triggered" if triggered else
                       "insufficient" if missing else
                       "not_triggered" if applicable.get(code, True) else
                       "not_applicable")
        risk_candidates.append(dict(
            code=code,
            name=(spec or {}).get("name") or (triggered or {}).get("name") or code,
            rule=(spec or {}).get("rule") or "",
            condition=(spec or {}).get("condition") or "",
            ontologyDescription=(spec or {}).get("description") or "",
            ruleStatus=rule_status,
            level=(triggered or {}).get("level") or "",
            title=(triggered or {}).get("title") or (spec or {}).get("name") or code,
            description=(triggered or {}).get("description") or (spec or {}).get("description") or "",
            metricCodes=(triggered or {}).get("metricCodes") or [],
            impact=(triggered or {}).get("impact") or {},
            evidenceIds=list(dict.fromkeys(
                (triggered or {}).get("evidenceIds") or [item["id"] for item in fact_items]))[:20],
            observed=[dict(id=item["id"], label=item.get("label"), value=item.get("value"),
                           unit=item.get("unit")) for item in fact_items],
            missingEvidence=missing,
        ))
    risk_assessments = [_program_risk_assessment(candidate) for candidate in risk_candidates]

    # ---- causes -----------------------------------------------------------
    # BR-C01: C01 no longer filters on demand confirmation (that is a drill-
    # down).  BR-C07: C06 is a non-focus, P0, unsigned opportunity whose
    # new_demandinput = 0; an empty value is not evidence either way.
    strategic_p0 = [opp for opp in unsigned if opp.get("tier") == "strategic" and opp.get("stage") == "11"
                    and _in_storage(opp)]
    p2_late = [opp for opp in unsigned if opp.get("stage") == "13" and opp in late_p2]
    p2_late = list({opp.get("id"): opp for opp in p2_late if opp.get("id")}.values())
    focus_ratio = _div(focus_amount, unsigned_amount) if unsigned_amount else None
    rest_amount = (unsigned_amount - (focus_amount or 0)) if unsigned_amount is not None else None
    rest_ratio = _div(rest_amount, unsigned_amount) if unsigned_amount else None
    rest_p0 = [opp for opp in unsigned if opp.get("tier") not in {"strategic", "priority"}
               and opp.get("stage") == "11" and opp.get("demandInput") == "0" and _in_storage(opp)]
    product_pending_ratio = {}
    for key in ("1", "2"):
        bucket = products[key]
        product_pending_ratio[key] = _div(bucket.get("pending_amount"), bucket.get("total_amount")) if bucket.get("total_amount") else None

    activity_config = (config.get("overrides") or {}).get("recentActivity") or {}
    window_days = _number(activity_config.get("windowDays"))
    recent_days = (max(1, min(int(window_days), 730))
                   if window_days is not None else None)
    recent_floor = (measured - timedelta(days=recent_days)
                    if recent_days is not None else None)

    def recent_activity(account):
        dates = [
            _day(account.get("lastVisitAt")),
            _day(account.get("latestActivityAt")),
            _day(account.get("latestLeadAt")),
            _day(account.get("latestLeadProgressAt")),
        ]
        if recent_floor is None:
            return False
        active_dates = [item for item in dates if item and item <= measured]
        return any(item >= recent_floor for item in active_dates)

    activity_source_ready = (bool(activity_config) and accounts_complete
                             and recent_floor is not None)
    no_recent_activity = ([account for account in no_opportunity
                           if not recent_activity(account)]
                          if activity_source_ready else [])

    candidates = {}
    if strategic_p0:
        amount = _sum(opp.get("forecastAmount") for opp in strategic_p0)
        energy = _sum(opp.get("forecastEnergy") for opp in strategic_p0)
        candidates["RC01"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="战略客户需求确认未落实",
            description=f"{len(strategic_p0)} 条战略客户 P0 商机尚未签单，涉及" +
                        (f"预测金额 {amount:.2f} 亿元" if amount else "预测量待补") +
                        (f"、预测电量 {energy:.2f} GWh" if energy else "") + "。",
            evidence=[f_r04_count, f_r04_a, f_r04_e] + top_opps(strategic_p0, 6),
            risks={"RK01", "RK02", "RK03", "RK06", "RK08", "RK10"} & {risk["code"] for risk in risks},
        )
    if p2_late:
        amount = _sum(opp.get("forecastAmount") for opp in p2_late)
        energy = _sum(opp.get("forecastEnergy") for opp in p2_late)
        candidates["RC03"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="方案推动超期",
            description=f"{len(p2_late)} 条商机处于 P2 且超过同产品动态平均周期 1.5 倍，涉及" +
                        (f"金额 {amount:.2f} 亿元" if amount else "金额待补") +
                        (f"、电量 {energy:.2f} GWh" if energy else "") + "。",
            evidence=[f_p2, f_rk10] + top_opps(p2_late, 6),
            risks={"RK04", "RK05"} & {risk["code"] for risk in risks},
        )
    concentration = {key: ratio for key, ratio in product_pending_ratio.items()
                     if ratio is not None and ratio >= thresholds["productPendingRatio"]}
    if concentration:
        parts = [f"{_product_name(key, config)} 待签占比 {ratio * 100:.1f}%" for key, ratio in concentration.items()]
        candidates["RC05"] = dict(
            kind="structure", status="hypothesis", stage="opportunity",
            title="产品结构待签集中",
            description="；".join(parts) + "；仅作结构定位，不能单独证明转化受阻。",
            evidence=[f_r05_a, f_r05_e, f_r06_a, f_r06_e],
            risks={"RK04", "RK05"} & {risk["code"] for risk in risks},
        )
    if focus_ratio is not None and focus_ratio < thresholds["focusTrackingRatio"] and unsigned_amount:
        candidates["RC06"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="重点跟踪商机承接不足",
        description=f"重点跟踪未签单商机占全部未签单预测 {focus_ratio * 100:.1f}%，低于 {thresholds['focusTrackingRatio'] * 100:.0f}% 阈值。",
            evidence=[f_r04_a, f_r04_e, f_r02_a, f_r02_e],
            risks={"RK01", "RK02"} & {risk["code"] for risk in risks},
        )
    if rest_ratio is not None and rest_ratio >= thresholds["otherPendingRatio"] and rest_p0:
        amount = _sum(opp.get("forecastAmount") for opp in rest_p0)
        candidates["RC07"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="其余商机需求未确认",
            description=f"一般客户未签单预测占比 {rest_ratio * 100:.1f}%，其中 {len(rest_p0)} 条 P0 商机未录入客户需求" +
                        (f"，涉及金额 {amount:.2f} 亿元" if amount else "") + "。",
            evidence=[f_r02_a, f_r02_e] + top_opps(rest_p0, 6),
            risks={"RK01", "RK02", "RK03"} & {risk["code"] for risk in risks},
        )
    if late_p0:
        candidates["RC08"] = dict(
            kind="structure", status="hypothesis", stage="opportunity",
            title="商机获取环节卡点",
            description=f"{len(late_p0)} 条商机 P0 周期超过动态均值 1.5 倍；细分卡点缺少结构化事件字段，仅作环节定位。",
            evidence=[f_p0, f_rk10] + top_opps(late_p0, 6),
            risks={"RK01", "RK10"} & {risk["code"] for risk in risks},
        )
    if no_opportunity:
        activity_evidence = [f_r09]
        for account in (no_recent_activity or [])[:8]:
            activity_evidence.append(record(
                f"opp-v2:account:{account.get('id')}:activity",
                customer=account.get("name"),
                status=f"近 {recent_days} 天无线索、拜访或销售活动",
                value=account.get("id"), name=account.get("name"),
            ))
        candidates["RC09"] = dict(
            kind="verified" if activity_source_ready else "data_gap",
            status="supported" if activity_source_ready else "insufficient",
            stage="opportunity",
            title="战略客户开拓不足",
            description=(
                f"{len(no_recent_activity)} 家无商机战略客户在近 {recent_days} 天无线索、拜访或销售活动记录。"
                if activity_source_ready else
                f"{len(no_opportunity)} 家战略客户当前无商机；近期线索、拜访及需求调研来源未完整接入，不能确认开拓不足。"
            ),
            evidence=activity_evidence,
            risks={"RK07"} & {risk["code"] for risk in risks},
            missingEvidence=[] if activity_source_ready else ["近期线索", "拜访", "需求调研"],
        )

    # Text-only prerequisites: only report when project progress actually
    # contains a checked blocker phrase.  No text means no RC02 claim.
    prerequisite_words = ("资质", "付款", "价格", "商务", "技术协议", "规格", "认证", "测试", "方案未")
    prerequisite_opps = []
    progress_samples = []
    for opp in opps:
        if opp.get("bidding") not in {"no", "ambiguous"}:
            continue
        for item in progress.get(opp.get("id"), [])[:5]:
            text = f"{item.get('description')}；{item.get('questionResource')}"
            if any(word in text for word in prerequisite_words):
                opp["_progressText"] = text[:500]
                prerequisite_opps.append(opp)
                break
    if prerequisite_opps:
        candidates["RC02"] = dict(
            kind="hypothesis", status="hypothesis", stage="bid",
            title="投标前置条件未满足",
            description=f"{len(prerequisite_opps)} 条未投标商机的项目进展文本提到商务或技术前置条件，需人工复核。",
            evidence=[],
            risks={"RK08", "RK09"} & {risk["code"] for risk in risks},
        )
        for opp in prerequisite_opps[:6]:
            for item in progress.get(opp.get("id"), [])[:3]:
                text = f"{item.get('description')}；{item.get('questionResource')}".strip("；")
                if text:
                    record_id = record(
                        f"opp-v2:progress:{item.get('id')}", customer=opp.get("accountName"),
                        status="项目进展", value=text[:240], evidence=item.get("id"))
                    candidates["RC02"]["evidence"].append(record_id)
                    progress_samples.append(dict(
                        evidenceId=record_id, opportunityId=opp.get("id"),
                        account=opp.get("accountName"), text=text[:500],
                    ))
                    break
        if not candidates["RC02"]["evidence"]:
            candidates["RC02"]["evidence"] = [f_r10]

    cause_outcomes = _cause_rule_outcomes(
        candidates=candidates, data=data, thresholds=thresholds, source_ok=source_ok,
        unsigned=unsigned, opps=opps, late_p0=late_p0, overall_p0=overall_p0,
        p2_mean_known=bool(late_p2) or any(opp.get("stage") == "13" for opp in opps),
        focus_ratio=focus_ratio, rest_ratio=rest_ratio,
        product_pending_ratio=product_pending_ratio, no_opportunity=no_opportunity,
        activity_source_ready=activity_source_ready, progress=progress,
        strategic_pending=[opp for opp in opps if opp.get("tier") == "strategic"
                           and opp.get("bidding") in {"no", "ambiguous"}],
        record=record, fact=fact)

    # Candidate risks are always intersected with the reviewed
    # risk→cause link table.  The workbook's cause sheet still lists doubtful
    # links (for example RK07→RC01); the runtime override must win so a card
    # cannot show a cause the same ontology explicitly removed.
    allowed_by_cause = defaultdict(set)
    for risk_code, link in (config.get("links") or {}).items():
        for cause_code in link.get("causes") or []:
            allowed_by_cause[cause_code].add(risk_code)
    active_risk_codes = {risk["code"] for risk in risks}
    for code in list(candidates):
        candidates[code]["risks"] = (set(candidates[code].get("risks") or [])
                                     & allowed_by_cause.get(code, set()) & active_risk_codes)
        if not candidates[code]["risks"]:
            candidates.pop(code)

    # Choose at most one cause per displayed risk first, then fill.  This keeps
    # the risk→cause relation explicit without forcing a one-to-one count.
    displayed = risks[:4]
    displayed_codes = [risk["code"] for risk in displayed]
    displayed_code_set = set(displayed_codes)
    chosen = []
    for risk_code in displayed_codes:
        ordered = [code for code in candidates if risk_code in candidates[code]["risks"]]
        ordered.sort(key=lambda code: (0 if candidates[code]["kind"] == "verified" else 1, code))
        for code in ordered:
            if code not in chosen:
                chosen.append(code)
                break
    for code in sorted(candidates, key=lambda item: (0 if candidates[item]["kind"] == "verified" else 1, item)):
        if len(chosen) >= 4:
            break
        if code not in chosen and candidates[code]["risks"] & set(displayed_codes):
            chosen.append(code)

    cause_items = []
    for code in chosen:
        candidate = candidates[code]
        finding_ids = [risk["id"] for risk in displayed if risk["code"] in candidate["risks"]]
        if not finding_ids:
            continue
        cause_id = f"opp-v2:cause:{code}"
        description = re.sub(r"\s+", " ", candidate["description"]).strip()[:160]
        cause_items.append(dict(
            id=cause_id, causeCode=code, kind=candidate["kind"], status=candidate["status"],
            stage=candidate["stage"], title=candidate["title"], description=description,
            findingIds=finding_ids, evidenceIds=list(dict.fromkeys(candidate["evidence"]))[:20],
            missingEvidence=list(candidate.get("missingEvidence") or []),
        ))

    # ---- advice -----------------------------------------------------------
    selected_codes = {cause["causeCode"] for cause in cause_items}
    advice_codes = []
    for cause in cause_items:
        for code, template in (config.get("advice") or {}).items():
            if cause["causeCode"] in (template.get("causes") or []) and code not in advice_codes:
                advice_codes.append(code)
    for risk in displayed:
        link = (config.get("links") or {}).get(risk["code"]) or {}
        if not (set(link.get("causes") or []) & selected_codes):
            for code in link.get("advice") or []:
                if code not in advice_codes:
                    advice_codes.append(code)
    advice_codes = [code for code in advice_codes if code in (config.get("advice") or {})]
    # Keep data-governance actions available but behind business remediation.
    advice_codes = ([code for code in advice_codes if code not in _GOVERNANCE_ADVICE]
                    + [code for code in advice_codes if code in _GOVERNANCE_ADVICE])[:4]
    if not advice_codes and displayed:
        advice_codes = (["AC01"] if "AC01" in (config.get("advice") or {})
                        else list(config.get("advice") or {})[:1])

    strategic_count = len({account.get("id") for account in no_opportunity + no_bidding if account.get("id")})
    cause_by_code = {cause["causeCode"]: cause for cause in cause_items}
    recommendations = []
    for code in advice_codes:
        template = (config.get("advice") or {}).get(code) or {}
        linked_causes = [cause for cause in cause_items
                         if cause["causeCode"] in ((config.get("advice") or {}).get(code, {}) or {}).get("causes", [])]
        action = _advice_action(code, template, dict(
            strategic_count=strategic_count, no_opportunity=len(no_opportunity),
            no_bidding=len(no_bidding), focus_count=focus_count,
            focus_ratio=focus_ratio, product_pending=product_pending_ratio,
            rest_p0=len(rest_p0), late_p0=len(late_p0), late_p2=len(p2_late),
            bid_late=len(late_bids), risks=displayed,
            focus_threshold=thresholds["focusTrackingRatio"],
        ))
        if not action:
            continue
        evidence_ids = []
        for cause in linked_causes:
            evidence_ids.extend(cause.get("evidenceIds") or [])
        evidence_ids = list(dict.fromkeys(evidence_ids)) or [risk["evidenceIds"][0] for risk in displayed if risk.get("evidenceIds")][:1]
        if not evidence_ids:
            continue
        linked_risk_codes = sorted({risk_code for cause in linked_causes
                                    for risk_code in candidates[cause["causeCode"]]["risks"]})
        risk_codes = [risk_code for risk_code in linked_risk_codes if risk_code in displayed_code_set]
        if not risk_codes:
            risk_codes = [risk["code"] for risk in displayed
                          if code in ((config.get("links") or {}).get(risk["code"], {}) or {}).get("advice", [])]
        if not risk_codes:
            risk_codes = linked_risk_codes
        deadline_days, deadline_type, deadline_text = _deadline_meta(template.get("deadline"))
        recommendations.append(dict(
            id=f"opp-v2:advice:{code}", adviceCode=code,
            actionType=_advice_action_type(code, template, linked_causes),
            governance=code in _GOVERNANCE_ADVICE,
            causeIds=[cause["id"] for cause in linked_causes], evidenceIds=evidence_ids[:20],
            action=action[:64], ownerRole=(template.get("owner") or "待确认")[:40],
            object=(template.get("object") or "")[:120],
            targetValue=(template.get("target") or "")[:180],
            tracking=(template.get("tracking") or "")[:180],
            priority=(template.get("priority") or "")[:20],
            deadline=deadline_text[:80], deadlineType=deadline_type,
            deadlineDays=deadline_days, acceptance=_acceptance(code, template)[:180],
            detail=(template.get("measure") or "")[:600], ownerConfirmed=False, deadlineConfirmed=False,
            riskCodes=risk_codes, linkedRiskCodes=linked_risk_codes or risk_codes,
        ))
    if not recommendations and displayed:
        risk = displayed[0]
        recommendations.append(dict(
            id="opp-v2:advice:investigate", adviceCode="INVESTIGATE", actionType="investigation",
            causeIds=[], evidenceIds=risk["evidenceIds"][:1], action=f"核查{risk['name']}的影响客户与预测口径"[:64],
            ownerRole="销售运营", deadline="10 个工作日", deadlineType="days", deadlineDays=10,
            acceptance="形成受影响客户、商机与预测量的可核对清单",
            detail="", ownerConfirmed=False, deadlineConfirmed=False,
            riskCodes=[risk["code"]], linkedRiskCodes=[risk["code"]],
        ))

    # ---- card result ------------------------------------------------------
    findings = []
    for risk in displayed:
        findings.append(dict(
            id=risk["id"], kind="risk_fact", title=risk["title"][:80],
            description=risk["description"][:320], metricCodes=risk["metricCodes"][:12],
            evidenceIds=risk["evidenceIds"][:20] or [next(iter(evidence_facts))],
            riskDomain="sales", riskCode=risk["code"], riskLevel=risk["level"],
            riskTotalCount=len(risks),
        ))
    dimensions = []
    for cause in cause_items:
        dimensions.append(dict(
            id=cause["id"], stage=cause["stage"], title=cause["title"][:32],
            description=cause["description"][:240], findingIds=cause["findingIds"],
            evidenceIds=cause["evidenceIds"], causeCode=cause["causeCode"],
            kind=cause["kind"], status=cause["status"],
        ))
    if not dimensions and findings:
        for finding in findings:
            dimensions.append(dict(
                id=f"dimension-{finding['id'].rsplit(':', 1)[-1]}", stage="opportunity",
                title=finding["title"][:32], description=finding["description"][:240],
                findingIds=[finding["id"]], evidenceIds=finding["evidenceIds"][:20],
            ))
    dimensions = dimensions[:4]

    summary_parts = []
    if target_amount is not None and total_amount is not None:
        summary_parts.append(
            f"年度目标 {target_amount:.2f} 亿元，商机获取 {total_amount:.2f} 亿元，"
            f"缺口 {target_amount - total_amount:.2f} 亿元")
    elif target_energy is not None and total_energy is not None:
        summary_parts.append(
            f"年度电量目标 {target_energy:.2f} GWh，商机获取 {total_energy:.2f} GWh，"
            f"缺口 {target_energy - total_energy:.2f} GWh")
    for risk in displayed[:2]:
        description = re.sub(r"\bRK\d+\b\s*", "", risk.get("description") or "").strip("。； ")
        if any(token in description for token in ("口径", "证据", "字段", "取数", "排查")):
            description = ""
        impact = risk.get("impact") or {}
        amount, energy, count = (_number(impact.get("amount")), _number(impact.get("energy")),
                                 _number(impact.get("count")))
        if not description:
            if amount is not None:
                description = f"影响金额 {amount:.2f} 亿元"
            elif count is not None:
                description = f"涉及 {int(count)} 项"
            elif energy is not None:
                description = f"影响电量 {energy:.2f} GWh"
        summary_parts.append(f"{risk.get('name') or '商机风险'}：{description}" if description
                             else (risk.get('name') or "商机风险"))
    summary = ("；".join(part for part in summary_parts if part).rstrip("。；") + "。"
               if summary_parts else
               "本期未发现需要优先处置的商机风险，未签单与预测差异继续按证据跟踪。")
    summary = re.sub(r"\s+", " ", summary)[:240]

    data_issues = []
    caliber_notes = []
    # The bid part can be excluded from the ontology config; then no bid
    # wording is published either.
    bid_enabled = bool({"RK08", "RK09"} & set(config.get("risks") or {}))
    if not strategic_ok:
        data_issues.append(
            "战略客户名单未配置：" + strategic_reason +
            f"；战略客户数量、无商机{'及未投标' if bid_enabled else ''}判断未执行，不按客户等级推算。")
    if strategic_ok and recent_floor is None:
        data_issues.append("本体 BR-C09 未定义“近期”窗口，战略客户开拓原因的近期活动判断未执行。")
    if total_energy is None and total_amount is not None:
        data_issues.append(
            f"本体 B02 电量口径 {energy_field} 本次没有有效值；电量相关阈值和风险未判定。")
    if data.get("errors"):
        data_issues.append("部分可选查询未返回：" + "、".join(sorted({item.get('stage') or item.get('code') or '未知' for item in data["errors"]})))
    if aggregate_mode and not aggregate_ready:
        data_issues.append(
            "商机明细达到行数上限，全量聚合未返回；截断明细不参与金额、电量、合同、产品、客户和风险规则计算。")
    elif not detail_complete:
        data_issues.append(
            "商机月度明细达到行数上限；明细仅用于展示，金额、电量、合同、产品、客户规则采用全量聚合；逐条周期和项目进展规则未判定。")
    if not all_opps_complete:
        data_issues.append(
            f"全部商机明细达到行数上限；战略客户无商机{'、未投标' if bid_enabled else ''}等逐客户判断未执行，避免把截断样本当成全量。")
    if bid_enabled and not bids_complete:
        data_issues.append("投标明细达到行数上限；投标周期和投标中项目相关规则未判定。")
    caliber_notes.extend([
        "签单按本体 BR-Q02 判断：商机经订单明细关联到订单即已签单，否则未签单。",
        "签单进度按已签单覆盖率计算（已签单商机预测 ÷ 商机预测总额，金额、电量分别计算）；年度目标只用于预测缺口。",
        "目标按本体 B01：同一商机（商机为空时按目标 ID）同一年度只取最新一条，再按客户、产品汇总。",
        f"预测电量按本体 B02 使用 {energy_field}"
        + ("（预测金额 ÷ 瓦时单价）" if _text(energy_cfg.get("mode")) == "amount_div_price" else f"（{energy_unit}）")
        + f"换算 {energy_cfg.get('outputUnit') or 'GWh'}。",
        "项目阶段、产品类型与客户等级按本体维度派生规则映射；其他枚举不推断。"
        + ("投标关联按本体 BR-Q07 使用商机名称与投标项目名称原值精确匹配；同名歧义不判未投标。"
           if bid_enabled else ""),
        "RC04 产品部销售缺口需跨发货环节实际销售，本次不把不可得数据推成原因。",
        "动态均值按本体 BR-Q06 执行：" + (clean_cycle_sample or "样本范围未提供") + "。",
        "建议中的责任角色与期限为模型给出的建议值，须人工确认后才能下发任务令。",
    ])
    if unknown_contract_count:
        data_issues.append(
            f"{unknown_contract_count} 条商机签单状态未知，涉及预测金额 {unknown_amount or 0:.2f} 亿元、"
            f"电量 {unknown_energy or 0:.2f} GWh；未知单列，既不计入明确未确认，也不视为已签。")
    limitations.extend(data_issues)
    limitations.extend(caliber_notes)

    result = dict(
        summary=summary,
        businessSummary=summary,
        findings=findings,
        causes=[dict(
            id=cause["id"], causeCode=cause["causeCode"], kind=cause["kind"],
            title=cause["title"], description=cause["description"], stage=cause["stage"],
            status=cause["status"], findingIds=cause["findingIds"], evidenceIds=cause["evidenceIds"],
            riskCodes=[code for code in sorted(candidates[cause["causeCode"]]["risks"])
                       if code in displayed_code_set],
            linkedRiskCodes=sorted(candidates[cause["causeCode"]]["risks"]),
            missingEvidence=list(cause.get("missingEvidence") or []),
        ) for cause in cause_items],
        analysisDimensions=dimensions,
        recommendations=recommendations,
        limitations=list(dict.fromkeys(limitations))[:10],
        caliberNotes=list(dict.fromkeys(caliber_notes))[:12],
        dataDiagnostics=list(dict.fromkeys(data_issues))[:12],
        riskTotalCount=len(risks),
        riskCodes=[risk["code"] for risk in risks],
        riskLevels={risk["code"]: risk["level"] for risk in risks},
        riskCandidateCount=len(risk_candidates),
        analysedRiskCount=len(risk_assessments),
        includedRiskCount=len(risks),
        riskAssessments=deepcopy(risk_assessments),
        excludedRiskCodes=[item["code"] for item in risk_assessments if not item.get("include")],
        modelExcludedRiskCodes=[],
        ontologyVersion=config.get("version"),
        ontologyTrace=_ontology_trace(config),
        queryCatalog=deepcopy(data.get("queryCatalog") or []),
        sourceConfigDigest=config_digest(),
        measurementDate=data.get("measurementDate"),
    )
    cause_candidates = [dict(
        code=code,
        title=candidate.get("title") or code,
        description=candidate.get("description") or "",
        kind=candidate.get("kind") or "hypothesis",
        status=candidate.get("status") or "hypothesis",
        stage=candidate.get("stage") or "opportunity",
        evidenceIds=list(dict.fromkeys(candidate.get("evidence") or []))[:20],
        riskCodes=sorted(candidate.get("risks") or []),
        missingEvidence=list(candidate.get("missingEvidence") or []),
        ruleStatus="triggered",
    ) for code, candidate in sorted(candidates.items())]
    # The ontology's risk→cause chain is model context even when a cause rule
    # did not fire: the model may still find that cause in this round's
    # evidence, citing the linked risk's evidence.  Rule outcome stays visible.
    for code, spec in sorted((config.get("causes") or {}).items()):
        if code in candidates:
            continue
        linked = sorted(allowed_by_cause.get(code, set()) & active_risk_codes)
        if not linked:
            continue
        cause_candidates.append(dict(
            code=code, title=spec.get("name") or code,
            description="；".join(_text(part) for part in (
                spec.get("condition"), spec.get("aiFocus")) if _text(part) and _text(part) != "—"),
            kind="hypothesis", status="hypothesis",
            stage=_CAUSE_STAGE.get(code, "opportunity"), evidenceIds=[],
            riskCodes=linked, missingEvidence=[], ruleStatus="not_triggered",
        ))
    advice_candidates = []
    risk_by_code = {risk["code"]: risk for risk in risks}
    cause_candidate_by_code = {item["code"]: item for item in cause_candidates}
    for code, template in sorted((config.get("advice") or {}).items()):
        cause_codes = [cause_code for cause_code in template.get("causes") or []
                       if cause_code in cause_candidate_by_code]
        risk_codes = {risk_code for cause_code in cause_codes
                      for risk_code in cause_candidate_by_code[cause_code]["riskCodes"]}
        for risk_code, link in (config.get("links") or {}).items():
            if code in (link.get("advice") or []) and risk_code in risk_by_code:
                risk_codes.add(risk_code)
        risk_codes &= set(risk_by_code)
        evidence_ids = []
        for cause_code in cause_codes:
            evidence_ids.extend(cause_candidate_by_code[cause_code]["evidenceIds"])
        if not evidence_ids:
            for risk_code in sorted(risk_codes):
                evidence_ids.extend(risk_by_code[risk_code].get("evidenceIds") or [])
        evidence_ids = list(dict.fromkeys(evidence_ids))[:20]
        if not risk_codes or not evidence_ids:
            continue
        deadline_days, deadline_type, deadline_text = _deadline_meta(template.get("deadline"))
        linked_causes = [cause for cause in cause_items if cause["causeCode"] in cause_codes]
        advice_candidates.append(dict(
            code=code,
            actionType=_advice_action_type(code, template, linked_causes),
            governance=code in _GOVERNANCE_ADVICE,
            name=template.get("name") or code,
            action=template.get("action") or template.get("name") or "",
            measure=template.get("measure") or "",
            object=template.get("object") or "",
            ownerRole=(template.get("owner") or "待确认")[:40],
            deadline=deadline_text[:80], deadlineType=deadline_type,
            deadlineDays=deadline_days,
            targetValue=template.get("target") or "",
            acceptance=_acceptance(code, template)[:180],
            tracking=template.get("tracking") or "",
            priority=template.get("priority") or "",
            causeCodes=cause_codes,
            riskCodes=sorted(risk_codes),
            evidenceIds=evidence_ids,
        ))
    # Facts of excluded ontology metrics (e.g. the bid part) are not published.
    excluded_metrics = set((config.get("excluded") or {}).get("metrics") or [])
    if {"R11", "S03"} & excluded_metrics:
        excluded_metrics |= {"S03-P1", "S03-P2", "BID-AMBIGUOUS"}
    for fact_code in excluded_metrics:
        evidence_facts.pop(f"opp-v2:metric:{fact_code}", None)
    cause_outcomes = {code: value for code, value in cause_outcomes.items()
                      if code in (config.get("causes") or {})}
    fact_list = list(evidence_facts.values())
    evidence_id_set = {str(item.get("id")) for key in ("facts", "records", "evidence")
                       for item in (fact_list if key == "facts" else
                                    records if key == "records" else evidence_refs)
                       if isinstance(item, dict) and item.get("id")}
    evidence_counts = dict(
        facts=len(fact_list), records=len(records), referenced=len(evidence_refs),
        distinct=len(evidence_id_set),
    )
    metric_values = dict(
        B01=dict(amount=target_amount, energy=target_energy),
        B02=dict(amount=total_amount, energy=total_energy),
        R01=dict(amount=gap_amount, energy=gap_energy),
        R02=dict(amount=unsigned_amount, energy=unsigned_energy,
                 unknownAmount=unknown_amount, unknownEnergy=unknown_energy,
                 confirmedAmount=confirmed_amount, confirmedEnergy=confirmed_energy),
        R03=dict(lagAmount=lag_amount, lagEnergy=lag_energy,
                 signProgressAmount=sign_progress_amount, signProgressEnergy=sign_progress_energy,
                 confirmedCoverageAmount=sign_progress_amount, confirmedCoverageEnergy=sign_progress_energy,
                 timeProgress=time_progress),
        R04=dict(count=focus_count, amount=focus_amount, energy=focus_energy),
        R05=dict(amount=products["1"]["pending_amount"], energy=products["1"]["pending_energy"]),
        R06=dict(amount=products["2"]["pending_amount"], energy=products["2"]["pending_energy"]),
        R08=dict(count=len(gap_accounts), pairs=len(customer_gaps)),
        R09=dict(count=no_opportunity_count),
        R10=dict(count=len(no_bidding)),
        R11=dict(count=len(in_progress_bids)),
        S03=bid_average, P0=overall_p0, P2=overall_p2,
        bidAmbiguous=len(ambiguous_bid_names),
    )
    for metric_code in excluded_metrics:
        metric_values.pop(metric_code, None)
    if "S03" in excluded_metrics:
        metric_values.pop("bidAmbiguous", None)
    return dict(
        causeOutcomes=cause_outcomes,
        ruleOutcomes=deepcopy(risk_candidates),
        riskCandidates=deepcopy(risk_candidates),
        riskAssessments=deepcopy(risk_assessments),
        causeCandidates=cause_candidates,
        adviceCandidates=advice_candidates,
        result=result,
        evidence=dict(
            facts=fact_list,
            records=records,
            evidence=evidence_refs,
            counts=evidence_counts,
            limitations=list(dict.fromkeys(limitations))[:10],
            periods=[data.get("period")],
            dataAsOf=data.get("measurementDate"),
        ),
        metrics=metric_values,
        risks=risks,
        causes=cause_items,
        recommendations=recommendations,
        textSamples=progress_samples if "RC02" in chosen else [],
    )


def _json_candidate(text):
    """Extract the first JSON object from a model response."""
    text = str(text or "").strip().lstrip("\ufeff")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start < 0:
        return ""
    try:
        _, end = json.JSONDecoder().raw_decode(text[start:])
        return text[start:start + end]
    except json.JSONDecodeError:
        end = text.rfind("}")
        return text[start:end + 1] if end >= start else text[start:]


def _decode_model_json(text, *, stop_reason=""):
    candidate = _json_candidate(text)
    if not candidate:
        raise ModelJSONOutputError("模型未返回 JSON", raw_text=text, stop_reason=stop_reason)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as first:
        # A trailing comma is a common LLM formatting error and can be
        # repaired without changing any facts or codes.
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            value = json.loads(cleaned)
        except json.JSONDecodeError:
            raise ModelJSONOutputError(
                f"模型 JSON 解析失败：{type(first).__name__}: {first}",
                raw_text=candidate, stop_reason=stop_reason,
            ) from first
    if not isinstance(value, dict):
        raise ModelJSONOutputError("模型 JSON 不是对象", raw_text=candidate, stop_reason=stop_reason)
    return value


def _looks_truncated_json(text):
    """Detect an unterminated object/string without trusting finish_reason."""
    text = str(text or "")
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)
    return in_string or depth > 0


# Optional per-analysis list of model calls; a caller sets it to collect a trace.
_CALL_TRACE = contextvars.ContextVar("opportunity_model_call_trace", default=None)


class ModelEmptyResponse(RuntimeError):
    """The model stream ended without any answer text."""

    def __init__(self, message, *, stop_reason="", finish_reason="", usage=None,
                 reasoning_chars=0, elapsed=0.0, max_tokens=0, timeout=0, tool_calls=()):
        super().__init__(message)
        self.tool_calls = list(tool_calls)
        self.stop_reason = stop_reason
        self.finish_reason = finish_reason
        self.usage = dict(usage or {})
        self.reasoning_chars = reasoning_chars
        self.elapsed = elapsed
        self.max_tokens = max_tokens
        self.timeout = timeout


def _read_model_stream(provider, messages, system_prompt, key, *, max_tokens, timeout,
                       step="生成分析"):
    from ..llm.runtime_config import request_config

    events = []
    stream_error = None
    started = time.monotonic()
    try:
        from ..llm.context_budget import cockpit_context_limit
        with request_config(thinking=False, request_timeout=timeout,
                            context_limit=cockpit_context_limit(),
                            min_output_tokens=min(max_tokens, 400)):
            # An empty allowlist means "no tools".  ``None`` would expose every
            # registered tool and let the model answer with a tool call
            # instead of the JSON analysis this step expects.
            for event in provider.stream_message(
                    messages, system_prompt, [], key,
                    max_tokens=max_tokens, temperature=0, thinking=False):
                events.append(event)
    except Exception as exc:  # noqa: BLE001 - keep a partially received answer
        stream_error = exc
    elapsed = time.monotonic() - started
    text = "".join(event.get("text", "") for event in events
                   if event.get("type") == "text_delta").strip()
    reasoning_chars = sum(len(event.get("text") or "") for event in events
                          if event.get("type") in {"thinking_block", "thinking_delta"})
    errors = [event.get("error", "") for event in events if event.get("type") == "error"]
    trace = _CALL_TRACE.get()
    if trace is not None:
        last_end = next((event for event in reversed(events)
                         if event.get("type") == "message_end"), {})
        trace.append(dict(
            step=step, route=_text(key), elapsedSeconds=round(elapsed, 1),
            timeoutSeconds=timeout, maxTokens=max_tokens,
            finishReason=_text(last_end.get("finish_reason")),
            stopReason=_text(last_end.get("stop_reason")),
            usage=dict(last_end.get("usage") or {}),
            ended=bool(last_end), textChars=len(text), reasoningChars=reasoning_chars,
            toolCalls=[dict(name=_text(event.get("name")),
                            input=json.dumps(event.get("input") or {}, ensure_ascii=False,
                                             default=str)[:200])
                       for event in events if event.get("type") == "tool_use_end"],
            error=(_text(errors[-1]) if errors else
                   f"{type(stream_error).__name__}: {stream_error}" if stream_error else ""),
            textHead=text[:600], textTail=text[-300:] if len(text) > 900 else "",
        ))
    if errors:
        if text:
            raise ModelJSONOutputError(
                f"模型流返回错误，已保留部分正文：{errors[-1]}",
                raw_text=text, stop_reason="stream_error",
            )
        raise RuntimeError(errors[-1])
    if stream_error is not None:
        if text:
            raise ModelJSONOutputError(
                f"模型流中断，已保留部分正文：{type(stream_error).__name__}: {stream_error}",
                raw_text=text, stop_reason="stream_error",
            ) from stream_error
        raise stream_error
    ends = [event for event in events if event.get("type") == "message_end"]
    end = ends[-1] if ends else {}
    if not text:
        stop = str(end.get("stop_reason") or "")
        finish = str(end.get("finish_reason") or "")
        usage = end.get("usage") or {}
        tool_calls = list(dict.fromkeys(
            _text(event.get("name")) for event in events
            if event.get("type") in {"tool_use_start", "tool_use_end"} and event.get("name")))
        facts = [f"结束原因 {finish or stop or '无（流没有正常结束）'}",
                 *([f"模型发起工具调用 {'、'.join(tool_calls)}"] if tool_calls else []),
                 f"推理内容 {reasoning_chars} 字",
                 f"输出 token {usage.get('output_tokens', '未知')} / 上限 {max_tokens}",
                 f"输入 token {usage.get('input_tokens', '未知')}",
                 f"耗时 {elapsed:.1f} 秒"]
        raise ModelEmptyResponse(
            "模型未返回正文（" + "，".join(facts) + "）",
            stop_reason=stop, finish_reason=finish, usage=usage,
            reasoning_chars=reasoning_chars, elapsed=elapsed,
            max_tokens=max_tokens, timeout=timeout, tool_calls=tool_calls)
    if not ends:
        raise ModelJSONOutputError(
            "模型流缺少结束事件，已保留部分正文",
            raw_text=text, stop_reason="stream_error",
        )
    return text, str(end.get("stop_reason") or ""), end.get("usage") or {}


_MODEL_KEY_ENV = "COCKPIT_OPPORTUNITY_V2_MODEL_KEY"
_MODEL_TIMEOUT_ENV = "COCKPIT_OPPORTUNITY_V2_MODEL_TIMEOUT_SECONDS"
_DEFAULT_MODEL_TIMEOUT_SECONDS = 180
_MAX_MODEL_TIMEOUT_SECONDS = 180


def _model_candidate_keys():
    """Use only the deployment-configured model, with an optional env override.

    The model id lives in ``TEAM_MODEL`` / the provider configuration, never in
    this module.  ``COCKPIT_OPPORTUNITY_V2_MODEL_KEY`` can pin a registry key
    or a model id when the configured route cannot disable thinking.
    """
    from ..llm.registry import ensure_team_model, get_default_model_key, get_model

    explicit = os.environ.get(_MODEL_KEY_ENV, "").strip()
    if explicit:
        return [explicit] if get_model(explicit) else [ensure_team_model(explicit)]
    return [get_default_model_key()]


def _model_route_name(key):
    try:
        from ..llm.registry import get_model
        return _text((get_model(key) or {}).get("model_id")) or _text(key)
    except Exception:  # noqa: BLE001 - context is best effort
        return _text(key)


def _annotate_model_error(exc, key, messages, started, timeout, max_tokens):
    """Attach the call context an operator needs to read a model failure."""
    exc.model_route = _model_route_name(key)
    exc.input_chars = sum(len(_text(message.get("content"))) for message in messages)
    exc.elapsed = round(time.monotonic() - started, 1)
    exc.timeout = timeout
    exc.max_tokens = max_tokens


def _model_numbers(value):
    return set(re.findall(r"(?<!\d)\d+(?:\.\d+)?(?!\d)", json.dumps(value, ensure_ascii=False, default=str)))


def _allowed_model_numbers(payload):
    """Accept harmless presentation variants, never an unrelated number.

    Models routinely render a stored ratio ``0.131`` as ``13.1%`` and round a
    long decimal to two places.  Those are not new facts.  The validator keeps
    every original token and adds only rounded/percentage forms of the original
    numbers, so an invented magnitude still fails.
    """
    allowed = _model_numbers(payload)
    extra = set()
    for token in list(allowed):
        try:
            value = float(token)
        except ValueError:
            continue
        variants = {value}
        for digits in (0, 1, 2, 3):
            variants.add(round(value, digits))
        if abs(value) <= 1:
            for digits in (0, 1, 2):
                variants.add(round(value * 100, digits))
        for variant in variants:
            extra.add(f"{variant:g}")
    return allowed | extra


def _model_items(value):
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(item, code=str(key)) for key, item in value.items() if isinstance(item, dict)]
    return []


def _model_error_context(exc, answer=None):
    """Facts about a failed model step; ``answer`` supplies them after a rejection."""
    trace = list(getattr(exc, "call_trace", None) or getattr(answer, "call_trace", None) or [])
    request = dict(getattr(exc, "request_info", None) or getattr(answer, "request_info", None) or {})
    return dict(
        modelCallTrace=trace, modelRequest=request,
        rejectionReasons=dict(getattr(exc, "reasons", None) or {}),
        modelRoute=(_text(getattr(exc, "model_route", ""))
                    or (_model_route_name(trace[-1]["route"]) if trace else "")),
        modelInputChars=getattr(exc, "input_chars", None) or request.get("inputChars"),
        modelElapsedSeconds=getattr(exc, "elapsed", None),
        modelTimeoutSeconds=getattr(exc, "timeout", None),
        modelMaxTokens=getattr(exc, "max_tokens", None),
        modelFinishReason=_text(getattr(exc, "finish_reason", "")),
        modelReasoningChars=getattr(exc, "reasoning_chars", None),
        modelToolCalls=list(getattr(exc, "tool_calls", None) or []),
        modelUsage=dict(getattr(exc, "usage", None) or {}),
        modelErrorType=type(exc).__name__,
    )


def _has(text, *words):
    return any(word in text for word in words)


def classify_model_failure(model_status):
    """Return (category, explanation, suggestion) for a stopped model step."""
    message = _text(model_status.get("modelErrorMessage"))
    lowered = message.lower()
    error = _text(model_status.get("error"))
    error_type = _text(model_status.get("modelErrorType"))
    stop = _text(model_status.get("modelStopReason")).lower()
    finish = _text(model_status.get("modelFinishReason")).lower()
    reasoning = model_status.get("modelReasoningChars") or 0
    timeout = model_status.get("modelTimeoutSeconds")
    if error == "MODEL_DISABLED":
        return ("未启用模型判断", "COCKPIT_OPPORTUNITY_V2_MODEL_ENABLED 已关闭，规则无法判定的条目不会交给模型。",
                "在 .env 中开启该开关后重新分析。")
    if _has(lowered, "context_length", "context length", "maximum context", "too many tokens",
            "prompt is too long", "input is too long", "token limit", "exceeds the model",
            "error code: 413", "上下文") or (_has(lowered, "too long") and "400" in lowered):
        return ("上下文超出模型限制", "本次发送给模型的输入超过了模型允许的上下文长度，请求被拒绝。",
                "换用上下文更长的模型，或减少发送的事实、记录和进展样本数量。")
    if "content_filter" in finish or _has(lowered, "content_filter", "content filter", "safety",
                                           "sensitive", "refus", "敏感", "违规", "审核"):
        return ("模型拒绝回答或内容被安全过滤", "模型服务因内容安全策略拦截了本次输出，没有返回正文。",
                "联系模型服务方确认过滤规则，或换用其他模型。")
    if _has(lowered, "error code: 401", "error code: 403", "unauthorized", "invalid api key",
            "incorrect api key", "authentication", "permission denied", "forbidden"):
        return ("模型服务认证失败", "模型服务拒绝了本次调用的凭据（API Key 无效、过期或无权限）。",
                "检查 .env 中的模型 API Key 与可用模型权限。")
    if _has(lowered, "error code: 429", "rate limit", "rate_limit", "too many requests", "quota",
            "insufficient_quota", "insufficient balance", "余额", "额度"):
        return ("模型服务限流或额度不足", "模型服务返回限流或额度不足，本次调用被拒绝。",
                "稍后重试，或联系模型服务方提高并发与额度。")
    if _has(lowered, "error code: 404", "model_not_found", "model not found", "does not exist",
            "no such model"):
        return ("模型不存在或名称配置错误", "模型服务找不到配置的模型名称。",
                "核对 TEAM_MODEL 或 COCKPIT_OPPORTUNITY_V2_MODEL_KEY 中的模型名。")
    if error_type == "ModelEmptyResponse" or "模型未返回正文" in message or "模型未返回完整文本" in message:
        tool_calls = model_status.get("modelToolCalls") or []
        if tool_calls or finish in {"tool_calls", "function_call"} or stop == "tool_use":
            return ("模型没有作答，而是发起了工具调用",
                    "模型返回的是工具调用" + (f"（{'、'.join(tool_calls)}）" if tool_calls else "")
                    + "，没有输出分析正文；这一步不应向模型提供任何工具。",
                    "这是程序问题而非模型故障：请升级到已修复的版本（分析请求不再附带工具）。")
        if reasoning:
            return ("模型只输出了推理过程，没有正文",
                    f"模型把输出预算用在了推理上（推理内容 {reasoning} 字），没有生成答案正文。",
                    "改用不带推理的模型路由（COCKPIT_OPPORTUNITY_V2_MODEL_KEY），或调大 "
                    "COCKPIT_OPPORTUNITY_V2_MODEL_MAX_TOKENS。")
        if stop in {"max_tokens", "length"} or finish == "length":
            return ("输出预算被耗尽", "模型达到输出 token 上限仍没有生成正文。",
                    "调大 COCKPIT_OPPORTUNITY_V2_MODEL_MAX_TOKENS，或换用不带推理的模型。")
        if not finish and not stop:
            return ("模型连接中途断开", "模型服务没有正常结束本次响应，也没有返回任何正文。",
                    "检查模型网关稳定性与超时设置后重试。")
        return ("模型返回为空", "模型正常结束了响应，但没有返回任何正文。",
                "确认模型服务是否正常；如持续出现，换用其他模型。")
    if _has(lowered, "timeout", "timed out", "time out", "超时", "readtimeout"):
        return ("模型请求超时", f"在 {timeout or '设定'} 秒内没有收到模型的后续输出。",
                "模型响应过慢或网络不稳定；可稍后重试，或换用更快的模型。")
    if _has(lowered, "connection", "connect", "name resolution", "refused", "unreachable",
            "ssl", "certificate", "network"):
        return ("无法连接模型服务", "网络或证书问题导致没有连上模型服务。",
                "检查服务器到模型地址的网络、代理与证书配置。")
    if _has(lowered, "error code: 500", "error code: 502", "error code: 503", "error code: 504",
            "internal server error", "bad gateway", "service unavailable", "overloaded"):
        return ("模型服务端异常", "模型服务返回了服务端错误。", "稍后重试；持续出现时联系模型服务方。")
    if error == "MODEL_OUTPUT_INVALID" or error_type == "ModelJSONOutputError":
        if stop in {"max_tokens", "length"} or _has(message, "token 上限"):
            return ("输出超过长度上限", "模型输出在达到 token 上限时被截断，JSON 不完整。",
                    "调大 COCKPIT_OPPORTUNITY_V2_MODEL_MAX_TOKENS，或换用输出更简洁的模型。")
        if stop == "stream_error" or _has(message, "流中断", "流返回错误", "缺少结束事件"):
            return ("模型输出中途中断", "模型已开始输出，但连接在输出完成前断开，结果不完整。",
                    "检查模型网关稳定性后重试。")
        if _has(message, "总预算已用尽"):
            return ("模型输出格式不对且没有时间修复", "模型返回的不是合法 JSON，剩余时间不够再发起修复。",
                    "换用响应更快、格式更稳定的模型。")
        return ("模型输出格式不对", "模型返回的内容不是要求的 JSON 格式，自动修复也没有成功。",
                "换用格式遵循更稳定的模型；原始返回片段见诊断记录。")
    if _has(lowered, "error code: 400", "invalid_request", "bad request", "unsupported", "invalid"):
        return ("模型拒绝了请求参数", "模型服务认为本次请求的参数不合法。",
                "核对模型名称与是否支持 thinking、max_tokens 等参数。")
    return ("模型调用失败", "模型调用没有成功，未能识别具体类型。", "按诊断 ID 查看完整错误后处理。")


def _deadline_meta(value):
    text = _text(value)
    match = re.search(r"(\d+)", text)
    if match and any(token in text for token in ("工作日", "天", "日")):
        return max(1, min(int(match.group(1)), 365)), "days", text
    return 30, "text", text or "待确认"


def _advice_action_type(code, template, linked_causes):
    """Governance actions are investigations, not business remediation."""
    if code in _GOVERNANCE_ADVICE or "治理" in ((template or {}).get("source") or ""):
        return "investigation"
    return ("remediation"
            if any(cause.get("kind") == "verified" and cause.get("status") == "supported"
                   for cause in linked_causes or [])
            else "investigation")


def _ontology_trace(config):
    """Expose the full ontology set used by this card for display and audit."""
    def entries(section, extra=()):
        values = []
        for code, item in (config.get(section) or {}).items():
            name = _text((item or {}).get("name")) or _text((item or {}).get("title")) or code
            value = dict(code=code, name=name)
            for key in extra:
                value[key] = _text((item or {}).get(key))
            values.append(value)
        return values

    return dict(
        ontology=_text(config.get("ontology")),
        version=_text(config.get("version")),
        digest=config_digest()[:12],
        links=deepcopy(config.get("links") or {}),
        metrics=entries("metrics", ("definition", "node", "stage", "unit",
                                    "resultColumns", "sqlStatus")),
        risks=entries("risks"),
        causes=entries("causes"),
        advice=entries("advice"),
        rules=entries("rules", ("description", "trigger", "result")),
    )


def _acceptance(code, template=None):
    return ((template or {}).get("acceptance")
            or "形成可核对的对象、数值、责任人与完成时间记录")


def _advice_action(code, template, values):
    strategic = values.get("strategic_count") or 0
    if code == "AC02":
        return f"对 {values.get('no_opportunity') or 0} 家无商机战略客户限期建立商机"
    if code == "AC03":
        return f"为 {strategic} 家战略客户逐户制定突破计划"
    if code == "AC10":
        ratio = values.get("focus_ratio")
        suffix = f"（当前 {ratio * 100:.1f}%）" if ratio is not None else ""
        target = round((values.get("focus_threshold") or 0.70) * 100)
        return f"将重点跟踪覆盖率提升至 {target}%{suffix}"
    return (template.get("action") or template.get("name") or template.get("measure") or "")[:64]


def _measurement_context(period, requested=None):
    measured = _measurement_date(period, requested)
    return measured


def _missing_supplement_fields(data):
    """List only metrics whose database value is absent, not genuine zero."""
    missing = []
    target = data.get("targets") or {}
    if _number(target.get("amount")) is None:
        missing.append("B01.amount")
    if _number(target.get("energy")) is None:
        missing.append("B01.energy")
    opps = data.get("opportunities") or []
    status = (data.get("queryStatus") or {}).get("商机预测")
    detail_complete = data.get("detailComplete", True)
    aggregate_ready = (data.get("aggregatesComplete", True)
                       and bool(data.get("opportunityAggregates")))
    if detail_complete and opps:
        if _sum(opp.get("forecastAmount") for opp in opps) is None:
            missing.append("B02.amount")
        if _sum(opp.get("forecastEnergy") for opp in opps) is None:
            missing.append("B02.energy")
    elif status in {"failed", "truncated"} and not aggregate_ready:
        missing.extend(("B02.amount", "B02.energy"))
    if ((data.get("strategicScope") or {}).get("available") is True
            and not data.get("accounts")
            and (data.get("queryStatus") or {}).get("客户") in {"failed", "truncated"}):
        missing.append("R09.count")
    return missing


def _ap_cell_values(body):
    payload = body.get("data", body) if isinstance(body, dict) else {}
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        result = payload if isinstance(payload, dict) else {}
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    found = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        for column in columns:
            code = _text((column or {}).get("identifierCode"))
            if not code:
                continue
            cell = row.get(code)
            if isinstance(cell, dict):
                cell = cell.get("value")
            number = _number(cell)
            if number is not None:
                found[code].append(number)
    return {code: _sum(values) for code, values in found.items()}


def default_ap_supplement(data):
    """Fill absent aggregate metrics from implemented AP contracts only.

    AP is never used to replace successful database values.  It answers just
    the missing target/forecast/count aggregates and never fabricates project
    rows, contract state or cause text.
    """
    missing = {field for field in _missing_supplement_fields(data)
               if field in _AP_SUPPLEMENT_CODES}
    if not missing:
        return {}
    from .ap_gateway import get_gateway
    from .query_capabilities import implemented_stage_requests

    gateway = get_gateway()
    wanted = {_AP_SUPPLEMENT_CODES[field] for field in missing}
    values = {}
    errors = []
    for request in implemented_stage_requests("opportunity", str(data.get("period") or "")):
        config = request.get("analysisConfig") or {}
        if config.get("dimensions"):
            continue
        codes = {_text(item.get("identifierCode")) for item in config.get("indicators") or []}
        if not codes & wanted:
            continue
        try:
            answer = gateway.query("analysis", request)
        except Exception as exc:  # noqa: BLE001 - partial AP fallback is allowed
            errors.append(type(exc).__name__)
            continue
        found = _ap_cell_values(answer)
        for field, code in _AP_SUPPLEMENT_CODES.items():
            if field in missing and field not in values and _number(found.get(code)) is not None:
                values[field] = _number(found[code])
        if all(field in values for field in missing):
            break
    result = {}
    for field, value in values.items():
        group, metric = field.split(".", 1)
        result.setdefault(group, {})[metric] = value
        result[group]["source"] = "AP 补充 · implemented opportunity aggregate"
    if not result:
        raise OpportunityV2Unavailable("AP 未返回可用的补充指标：" + "、".join(sorted(set(errors))[:4]))
    if errors:
        result["errors"] = sorted(set(errors))
    return result


def build_card(period, database=None, measurement_date=None, config=None, judge=None,
               supplement=None, progress=None, diagnostic_reporter=None, semantic=None):
    """Build one complete ``opportunity-risk`` publication payload.

    Rules first: risks, causes and advice are settled by the ontology rule
    functions; only an item a rule cannot settle is sent to the model, one
    item per call (``judge``).  A failed model call skips that item.  A failed
    database read fails the card: nothing stands in for missing data.
    """
    from .opportunity_judgement import control_risk_rows, judge_card, link_queries

    _report_progress(progress, "ontology", message="读取本体与规则配置")
    config = config or load_config()
    started = time.monotonic()
    measured = _measurement_context(period, measurement_date)
    strategic_ok, _ = _strategic_scope(config)
    _report_progress(progress, "fetching", message="查询数据库", completed=0,
                     total=9 if not strategic_ok else 10)
    try:
        data = collect(period, measured, database=database, config=config, progress=progress,
                       diagnostic_reporter=diagnostic_reporter)
    except OpportunityV2Unavailable as exc:
        if diagnostic_reporter is not None:
            try:
                diagnostic_reporter(dict(
                    phase=getattr(exc, "phase", "database_query"), query="database_core",
                    code=getattr(exc, "code", type(exc).__name__),
                    upstreamCode=getattr(exc, "upstream_code", ""),
                    message=getattr(exc, "diagnostic_message", str(exc)),
                    durationSeconds=round(time.monotonic() - started, 3),
                ))
            except Exception:  # noqa: BLE001 - diagnostics cannot fail the card
                pass
        raise
    missing = _missing_supplement_fields(data)
    supplement_errors = []
    if supplement is not None and missing:
        _report_progress(progress, "ap", message="AP 补充缺失聚合指标")
        try:
            supplied = supplement(data)
        except Exception as exc:  # noqa: BLE001 - AP supplementation is optional
            supplement_errors.append(type(exc).__name__)
            supplied = {}
        if supplied:
            data["supplement"] = {key: value for key, value in supplied.items() if key != "errors"}
            supplement_errors.extend(supplied.get("errors") or [])
    missing = _missing_supplement_fields(data)
    _report_progress(progress, "rules", message="规则函数判定风险与根因")
    evaluated = evaluate(data, config, measured)
    _report_progress(progress, "analysing", message="逐条判定规则无法确定的风险与根因")
    judged = judge_card(evaluated, config, judge=judge, progress=progress)
    # Once every risk is settled the model words all risk rows as one set;
    # numbers must match the rule-written rows or the row is kept as is.
    semantic_report = control_risk_rows(judged["findings"], config, semantic, progress=progress)
    fetched_at = time.time()
    result = evaluated["result"]
    result.update(judged)
    result["semanticControl"] = semantic_report
    link_queries(result, config)
    result["businessSummary"] = judged["summary"]
    result["cardContract"] = "cockpit-cards-v1"
    result["engine"] = "opportunity-v3-rules"
    result["analysisAssembly"] = dict(
        cardWriter="rules", modelContract="item-judgement-v1",
        modelCalls=judged["ontologyJudgement"]["modelCalls"],
        modelFailures=len(judged["ontologyJudgement"]["failures"]),
    )
    diagnostics = list(result.get("dataDiagnostics") or [])
    diagnostics += ["模型判断失败已跳过：" + item for item in judged["ontologyJudgement"]["failures"]]
    diagnostics += ["风险行语义控制：" + item for item in semantic_report.get("issues") or []]
    if data.get("supplement"):
        diagnostics.append("部分目标/预测指标来自 AP 补充，已在对应指标来源中标明；明细级风险不据 AP 聚合值推导。")
    if supplement_errors:
        diagnostics.append("AP 补充未全部成功：" + "、".join(sorted(set(supplement_errors))[:4]))
    result["dataDiagnostics"] = list(dict.fromkeys(diagnostics))[:20]
    _report_progress(progress, "publishing", message="发布卡片")
    skipped = bool(judged["ontologyJudgement"]["failures"])
    item = dict(
        id=uuid.uuid4().hex,
        status="limited" if (data.get("errors") or missing or skipped) else "completed",
        context=dict(
            stage="opportunity", slotId=SLOT_ID, period=str(period), id=1,
            dataFingerprint=hashlib.sha256(json.dumps(dict(
                period=str(period), measurementDate=measured.isoformat(),
                metrics=evaluated["metrics"], riskCodes=result["riskCodes"]), ensure_ascii=False,
                sort_keys=True, default=str).encode()).hexdigest(),
            ontologyVersion=config.get("version"), source="opportunity-v3",
            measurementDate=measured.isoformat(),
        ),
        result=result,
        evidence=evaluated["evidence"],
        metrics=evaluated["metrics"],
        risks=[risk for risk in evaluated["risks"] if risk.get("code") in result["riskCodes"]],
        execution=dict(
            engine="opportunity-v3-rules", durationSeconds=round(time.monotonic() - started, 3),
            queryDurationSeconds=data.get("durationSeconds"), fetchedAt=fetched_at,
            source="customer PostgreSQL", measurementDate=measured.isoformat(),
            rulesVersion=config.get("version"), configDigest=config_digest(),
            riskCount=len(result["riskCodes"]), errorCount=len(data.get("errors") or []),
            queryTimeoutMs=data.get("queryTimeoutMs"),
            fetchBudgetSeconds=data.get("fetchBudgetSeconds"),
            queryDiagnostics=data.get("queryDiagnostics") or [],
            evidenceCounts=evaluated["evidence"].get("counts") or {},
            modelCalls=judged["ontologyJudgement"]["modelCalls"],
            modelFailures=judged["ontologyJudgement"]["failures"],
            supplementMissing=missing,
            supplementErrors=sorted(set(supplement_errors))[:8],
        ),
        updatedAt=fetched_at,
    )
    return item


__all__ = [
    "SLOT_ID", "RULES_VERSION", "OpportunityV2Unavailable", "OpportunityV2ModelUnavailable", "load_config",
    "config_version", "config_digest", "collect", "evaluate", "build_card",
    "default_ap_supplement",
]
