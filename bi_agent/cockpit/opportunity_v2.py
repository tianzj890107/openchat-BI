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
from contextlib import nullcontext
from copy import deepcopy
from datetime import date, datetime, time as datetime_time, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

CONFIG_PATH = Path(__file__).parent / "assets/opportunity-v2/config.json"
SLOT_ID = "opportunity-risk"
RULES_VERSION = "opportunity-v2-rules-1"

_LEVEL_RANK = {"极高": 0, "高": 1, "中": 2, "低": 3}
_CAUSE_STAGE = {
    "RC01": "opportunity", "RC02": "bid", "RC03": "opportunity",
    "RC04": "opportunity", "RC05": "opportunity", "RC06": "opportunity",
    "RC07": "opportunity", "RC08": "opportunity",
}
_PRODUCT_NAMES = {"1": "电芯", "2": "PACK"}
_STAGE_NAMES = {"11": "P0 商机获取", "12": "P1 技术交流", "13": "P2 方案推动",
                "14": "P3 合同签订", "15": "P4 批量交付"}
_AP_SUPPLEMENT_CODES = {
    "B01.amount": "YWLN_M0002",
    "B02.amount": "YWLN_M0023",
    "B02.energy": "YWLN_M0022",
}
_CONFIG_CACHE: dict[str, tuple[int, dict]] = {}


class OpportunityV2Unavailable(RuntimeError):
    """The card cannot be produced without inventing evidence."""


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


def _customer_tier(level, config=None):
    level = _text(level)
    mapping = ((config or {}).get("overrides") or {}).get("customerTier") or {}
    for tier in ("strategic", "priority", "general"):
        if level in {_text(value) for value in mapping.get(tier) or []}:
            return tier
    return "unknown"


def _thresholds(config):
    value = ((config or {}).get("overrides") or {}).get("thresholds") or {}
    return dict(
        gapRateHigh=_number(value.get("gapRateHigh")) if _number(value.get("gapRateHigh")) is not None else 0.10,
        gapRateMedium=_number(value.get("gapRateMedium")) if _number(value.get("gapRateMedium")) is not None else 0.05,
        signLagExtremePoints=_number(value.get("signLagExtremePoints")) if _number(value.get("signLagExtremePoints")) is not None else 15,
        signLagHighPoints=_number(value.get("signLagHighPoints")) if _number(value.get("signLagHighPoints")) is not None else 10,
        quarterWindows=value.get("quarterWindows") or {"3": 0.50, "4": 0.25},
        focusTrackingRatio=_number(value.get("focusTrackingRatio")) if _number(value.get("focusTrackingRatio")) is not None else 0.70,
        productPendingRatio=_number(value.get("productPendingRatio")) if _number(value.get("productPendingRatio")) is not None else 0.20,
        otherPendingRatio=_number(value.get("otherPendingRatio")) if _number(value.get("otherPendingRatio")) is not None else 0.30,
        productRiskAmountHigh=_number(value.get("productRiskAmountHigh")) if _number(value.get("productRiskAmountHigh")) is not None else 30,
        productRiskAmountMedium=_number(value.get("productRiskAmountMedium")) if _number(value.get("productRiskAmountMedium")) is not None else 10,
    )


def load_config():
    """Load and validate the reviewed runtime config; never read the workbook."""
    stamp = CONFIG_PATH.stat().st_mtime_ns
    cached = _CONFIG_CACHE.get(str(CONFIG_PATH))
    if cached and cached[0] == stamp:
        return cached[1]
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("version") != RULES_VERSION:
        raise OpportunityV2Unavailable("商机 V2 运行配置版本不匹配")
    source = config.get("source") or {}
    # The authoring workbook is not shipped to customers.  When it is present
    # in a development checkout, verify it; the config hash always protects the
    # deployed artifact through the release version.
    source_path = Path(__file__).parents[2] / str(source.get("path") or "")
    if source.get("path") and source_path.exists():
        actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source.get("sha256") and actual != source["sha256"]:
            raise OpportunityV2Unavailable("商机 V2 本体源文件与运行配置哈希不一致")
    risks = set(config.get("risks") or {})
    causes = set(config.get("causes") or {})
    advice = set(config.get("advice") or {})
    for risk, link in (config.get("links") or {}).items():
        if risk not in risks:
            raise OpportunityV2Unavailable(f"V2 链路引用未知风险：{risk}")
        if not set(link.get("causes") or []) <= causes:
            raise OpportunityV2Unavailable(f"V2 链路引用未知根因：{risk}")
        if not set(link.get("advice") or []) <= advice:
            raise OpportunityV2Unavailable(f"V2 链路引用未知建议：{risk}")
    if "RK07" in (config.get("links") or {}) and (config["links"]["RK07"].get("causes") or []):
        raise OpportunityV2Unavailable("RK07 与 RC01 的矛盾关联未解除")
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
        raise OpportunityV2Unavailable("未配置商机 V2 只读数据库：" + config.ready()[1])
    return PostgresDatabase(config, max_rows=20000)


def _table(config, entity):
    table = _text((config.get("logicalEntities", {}).get(entity) or {}).get("table"))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", table):
        raise OpportunityV2Unavailable(f"V2 逻辑实体缺少合法物理表：{entity}")
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
        raise OpportunityV2Unavailable("商机 V2 只接受四位年度期间")
    return int(value)


def _report_progress(progress, phase, **detail):
    """Progress reporting is observational and must never break evidence work."""
    if progress is None:
        return
    try:
        progress(phase, **detail)
    except Exception:  # noqa: BLE001 - a UI callback cannot fail the analysis
        pass


def collect(period, measurement_date=None, database=None, config=None, progress=None):
    """Read fixed V2 facts from one repeatable-read PostgreSQL snapshot."""
    config = config or load_config()
    year = _safe_year(period)
    measured = _measurement_date(period, measurement_date)
    database = database or _database()
    if not database.available:
        raise OpportunityV2Unavailable(database.unavailable_reason())
    started = time.monotonic()
    errors: list[dict] = []
    query_status: dict[str, str] = {}
    schema = database.config.schema

    total_queries = 9
    completed_queries = 0

    def run(source, sql, params, *, optional=False, label=""):
        nonlocal completed_queries
        try:
            result = source.run(sql, params, timeout_ms=max(
                database.config.statement_timeout_ms,
                int(os.environ.get("COCKPIT_OPPORTUNITY_V2_QUERY_TIMEOUT_MS", "90000")),
            ))
            if getattr(result, "truncated", False):
                query_status[label or "optional"] = "truncated"
                errors.append(dict(stage=label or "optional", code="ROW_LIMIT"))
            else:
                query_status[label or "optional"] = "ok"
            return [dict(row) for row in result.rows]
        except Exception as exc:  # noqa: BLE001 - report a controlled limitation
            query_status[label or "optional"] = "failed"
            if not optional:
                raise OpportunityV2Unavailable(f"{label or 'V2 取数'}失败：{type(exc).__name__}") from None
            errors.append(dict(stage=label or "optional", code=type(exc).__name__))
            return []
        finally:
            completed_queries += 1
            _report_progress(progress, "fetching", message="查询数据库", completed=completed_queries,
                             total=total_queries)

    # The config contains physical names already validated against the reviewed
    # ontology.  SQL is assembled only from those names and fixed templates.
    target_table = _table(config, "LE06")
    target_cols = _columns(config, "LE06")
    months = [target_cols[f"new_month{i}"] for i in range(1, 13)]
    quantities = [target_cols[f"new_month{i}_quantity"] for i in range(1, 13)]
    amount_count = "+".join(f"COUNT(t.{col})" for col in months)
    energy_count = "+".join(f"COUNT(t.{col})" for col in quantities)
    target_sql = (
        f"SELECT COALESCE(t.{target_cols['new_producttype_id']}, '') AS product_type_id, "
        f"COALESCE(t.{target_cols['new_account_id']}, '') AS account_id, "
        f"CASE WHEN ({amount_count}) = 0 THEN NULL ELSE "
        f"SUM({'+'.join('COALESCE(t.' + col + ',0)' for col in months)}) END AS amount_yuan, "
        f"CASE WHEN ({energy_count}) = 0 THEN NULL ELSE "
        f"SUM({'+'.join('COALESCE(t.' + col + ',0)' for col in quantities)}) END AS energy_kwh, "
        f"({amount_count}) AS amount_cells, ({energy_count}) AS energy_cells, COUNT(*) AS rows "
        f"FROM {target_table} t WHERE t.{target_cols['new_year']} = %s "
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
    past = measured.month
    opp_sql = (
        f"WITH agg AS ("
        f" SELECT m.{mc['new_opportunity_id']} AS opportunity_id, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s "
        f" THEN m.{mc['new_amt_rmb']} ELSE m.{mc['new_forecast_amt_rmb']} END) AS amount_yuan, "
        f" SUM(m.{mc['new_forecast_amt_rmb']}) AS forecast_amount_full_yuan, "
        f" SUM(m.{mc['new_orderforecast_qty']}) / 1000000.0 AS energy_gwh, "
        f" COUNT(*) AS month_rows, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s THEN 1 ELSE 0 END) AS past_rows, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s "
        f" AND m.{mc['new_amt_rmb']} IS NOT NULL THEN 1 ELSE 0 END) AS past_amount_rows, "
        f" SUM(CASE WHEN m.{mc['new_orderforecast_qty']} IS NOT NULL THEN 1 ELSE 0 END) AS energy_rows "
        f" FROM {month_table} m "
        f" WHERE EXTRACT(YEAR FROM m.{mc['new_accountdate']})::int = %s "
        f" AND m.{mc['statecode']} = 0 AND m.{mc['new_approvalstatus']} = 3 "
        f" GROUP BY 1"
        f") SELECT o.{oc['opportunityid']} AS opportunity_id, o.{oc['name']} AS name, "
        f" COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f" COALESCE(a.{ac['name']}, '') AS account_name, "
        f" COALESCE(NULLIF(a.{ac['new_accountlevel']}::text, ''), o.{oc['new_accountlevel']}, '') AS account_level, "
        f" COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f" COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f" COALESCE(o.{oc['new_approvalstatus_acneed']}, '') AS acneed_status, "
        f" COALESCE(o.{oc['new_opportunitystatus']}, '') AS opportunity_status, "
        f" o.{oc['new_contractconfirmation']} AS contract_confirmation, "
        f" o.{oc['createdon']} AS created_at, o.{oc['new_stage1enddate']} AS stage1_end, "
        f" o.{oc['new_stage2enddate']} AS stage2_end, o.{oc['new_stage3enddate']} AS stage3_end, "
        f" o.{oc['new_stage4enddate']} AS stage4_end, o.{oc['new_stage5enddate']} AS stage5_end, "
        f" COALESCE(o.{oc['ownerid']}, '') AS owner_id, agg.amount_yuan, "
        f" agg.forecast_amount_full_yuan, agg.energy_gwh, "
        f" agg.month_rows, agg.past_rows, agg.past_amount_rows, agg.energy_rows "
        f" FROM {opp_table} o LEFT JOIN agg ON o.{oc['opportunityid']} = agg.opportunity_id "
        f" LEFT JOIN {account_table} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f" WHERE o.{oc['new_approvalstatus']} = '3' AND o.{oc['createdon']} <= %s"
    )

    all_opp_sql = (
        f"SELECT o.{oc['opportunityid']} AS opportunity_id, o.{oc['name']} AS name, "
        f"COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f"COALESCE(NULLIF(a.{ac['new_accountlevel']}::text, ''), o.{oc['new_accountlevel']}, '') AS account_level, "
        f"COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f"COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f"COALESCE(o.{oc['new_opportunitystatus']}, '') AS opportunity_status, "
        f"o.{oc['new_contractconfirmation']} AS contract_confirmation, "
        f"o.{oc['createdon']} AS created_at, o.{oc['new_stage1enddate']} AS stage1_end, "
        f"o.{oc['new_stage2enddate']} AS stage2_end, o.{oc['new_stage3enddate']} AS stage3_end, "
        f"o.{oc['new_stage4enddate']} AS stage4_end, o.{oc['new_stage5enddate']} AS stage5_end "
        f"FROM {opp_table} o LEFT JOIN {account_table} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f"WHERE o.{oc['new_approvalstatus']} = '3' AND o.{oc['createdon']} <= %s"
    )

    # Full aggregate fallback for truncated detail rows.  A truncated list can
    # still be displayed, but its partial sums must never drive risk rules.
    aggregate_sql = (
        f"WITH agg AS ("
        f" SELECT m.{mc['new_opportunity_id']} AS opportunity_id, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s "
        f" THEN m.{mc['new_amt_rmb']} ELSE m.{mc['new_forecast_amt_rmb']} END) AS amount_yuan, "
        f" SUM(m.{mc['new_forecast_amt_rmb']}) AS forecast_amount_full_yuan, "
        f" SUM(m.{mc['new_orderforecast_qty']}) / 1000000.0 AS energy_gwh, "
        f" COUNT(*) AS month_rows, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s THEN 1 ELSE 0 END) AS past_rows, "
        f" SUM(CASE WHEN EXTRACT(MONTH FROM m.{mc['new_accountdate']})::int < %s "
        f" AND m.{mc['new_amt_rmb']} IS NOT NULL THEN 1 ELSE 0 END) AS past_amount_rows, "
        f" SUM(CASE WHEN m.{mc['new_orderforecast_qty']} IS NOT NULL THEN 1 ELSE 0 END) AS energy_rows "
        f" FROM {month_table} m "
        f" WHERE EXTRACT(YEAR FROM m.{mc['new_accountdate']})::int = %s "
        f" AND m.{mc['statecode']} = 0 AND m.{mc['new_approvalstatus']} = 3 "
        f" GROUP BY 1"
        f") SELECT COALESCE(o.{oc['new_contractconfirmation']}::text, '') AS contract_raw, "
        f" COALESCE(NULLIF(a.{ac['new_accountlevel']}::text, ''), o.{oc['new_accountlevel']}, '') AS account_level, "
        f" COALESCE(o.{oc['new_accproducttype']}, '') AS product_type, "
        f" COALESCE(o.{oc['parentaccountid']}, '') AS account_id, "
        f" COALESCE(a.{ac['name']}, '') AS account_name, "
        f" COALESCE(o.{oc['new_processstage']}, '') AS process_stage, "
        f" COUNT(*) AS opportunity_count, "
        f" SUM(agg.amount_yuan) AS amount_yuan, SUM(agg.forecast_amount_full_yuan) AS forecast_amount_full_yuan, "
        f" SUM(agg.energy_gwh) AS energy_gwh, SUM(agg.month_rows) AS month_rows, "
        f" SUM(agg.past_rows) AS past_rows, SUM(agg.past_amount_rows) AS past_amount_rows, "
        f" SUM(agg.energy_rows) AS energy_rows "
        f" FROM {opp_table} o LEFT JOIN agg ON o.{oc['opportunityid']} = agg.opportunity_id "
        f" LEFT JOIN {account_table} a ON a.{ac['accountid']} = o.{oc['parentaccountid']} "
        f" WHERE o.{oc['new_approvalstatus']} = '3' AND o.{oc['createdon']} <= %s "
        f" GROUP BY 1,2,3,4,5,6"
    )

    accounts_sql = (
        f"SELECT a.{ac['accountid']} AS account_id, a.{ac['name']} AS name, "
        f"a.{ac['new_accountlevel']} AS account_level, a.{ac['createdon']} AS created_at "
        f"FROM {account_table} a"
    )

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

    # Order counts are supporting evidence only.  Contract confirmation remains
    # the signing decision; an order existing never proves a contract is signed.
    order_table = _table(config, "LE07")
    detail_table = _table(config, "LE08")
    order_cols = _columns(config, "LE07")
    detail_cols = _columns(config, "LE08")
    order_sql = (
        f"SELECT d.{detail_cols['new_opportunity_id']} AS opportunity_id, "
        f"COUNT(DISTINCT o.{order_cols['salesorderid']}) AS order_count, "
        f"SUM(o.{order_cols['new_contract_amt']}) AS order_amount "
        f"FROM {detail_table} d JOIN {order_table} o ON o.{order_cols['salesorderid']} = d.{detail_cols['salesorderid']} "
        f"WHERE d.{detail_cols['new_opportunity_id']} IS NOT NULL AND o.{order_cols['statecode']} = 0 "
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
    # forecast and bid facts observed at different times.
    snapshot = database.snapshot() if hasattr(database, "snapshot") else nullcontext(database)
    with snapshot as source:
        target_rows = run(source, target_sql, [year], optional=True, label="销售目标")
        product_rows = run(
            source,
            f"SELECT p.{product_cols['new_product_typeid']} AS product_type_id, "
            f"p.{product_cols['new_accproducttype']} AS product_type, p.{product_cols['new_name']} AS name "
            f"FROM {product_table} p",
            [], optional=True, label="产品类型",
        )
        opp_rows = run(source, opp_sql, [past, past, past, year, measured],
                       optional=True, label="商机预测")
        all_opp_rows = run(source, all_opp_sql, [measured], optional=True, label="全部商机")
        account_rows = run(source, accounts_sql, [], optional=True, label="客户")
        bid_rows_raw = run(source, bid_sql, [measured], optional=True, label="投标")
        progress_rows = run(source, progress_sql, [measured, measured],
                            optional=True, label="项目进展")
        order_rows = run(source, order_sql, [], optional=True, label="订单关联")
        team_rows = run(source, team_sql, [], optional=True, label="产品团队")
        aggregate_rows = []
        if (query_status.get("商机预测") == "truncated"
                or query_status.get("全部商机") == "truncated"):
            total_queries = 10
            aggregate_rows = run(source, aggregate_sql, [past, past, past, year, measured],
                                 optional=True, label="商机聚合")

    product_types = {_text(row.get("product_type_id")): _text(row.get("product_type"))
                     for row in product_rows}

    targets = dict(amount=None, energy=None, rows=0, amountCells=0, energyCells=0,
                   byProduct=defaultdict(lambda: dict(amount=0.0, energy=0.0, rows=0)),
                   byAccount={})
    for row in target_rows:
        amount = _number(row.get("amount_yuan"))
        energy = _number(row.get("energy_kwh"))
        energy = energy / 1_000_000.0 if energy is not None else None
        rows_count = int(_number(row.get("rows")) or 0)
        targets["amountCells"] += int(_number(row.get("amount_cells")) or 0)
        targets["energyCells"] += int(_number(row.get("energy_cells")) or 0)
        product_id = _text(row.get("product_type_id"))
        product = product_types.get(product_id, product_id)
        key = product if product in {"1", "2"} else "unknown"
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
    targets["amount"] = (round(targets["amount"] / 100_000_000.0, 6)
                         if targets["amount"] is not None else None)
    targets["energy"] = round(targets["energy"], 6) if targets["energy"] is not None else None
    for bucket in list(targets["byProduct"].values()) + list(targets["byAccount"].values()):
        bucket["amount"] = round((bucket.get("amount") or 0.0) / 100_000_000.0, 6)
        bucket["energy"] = round(bucket.get("energy") or 0.0, 6)

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
            productType=product if product in {"1", "2"} else "unknown",
            accountId=_text(row.get("account_id")),
            accountName=_text(row.get("account_name")),
            stage=_text(row.get("process_stage")),
            count=int(_number(row.get("opportunity_count")) or 0),
            amount=(_round(_number(row.get("amount_yuan")) / 100_000_000.0, 6)
                    if row.get("amount_yuan") is not None else None),
            amountFull=(_round(_number(row.get("forecast_amount_full_yuan")) / 100_000_000.0, 6)
                        if row.get("forecast_amount_full_yuan") is not None else None),
            energy=_round(row.get("energy_gwh"), 6),
            monthRows=int(_number(row.get("month_rows")) or 0),
            pastRows=int(_number(row.get("past_rows")) or 0),
            pastAmountRows=int(_number(row.get("past_amount_rows")) or 0),
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
        past_rows = int(_number(row.get("past_rows")) or 0)
        past_amount_rows = int(_number(row.get("past_amount_rows")) or 0)
        energy_rows = int(_number(row.get("energy_rows")) or 0)
        opportunities.append(dict(
            id=opp_id,
            name=_text(row.get("name")),
            accountId=_text(row.get("account_id")),
            accountName=_text(row.get("account_name")),
            accountLevel=level,
            tier=tier,
            productType=product if product in {"1", "2"} else "unknown",
            productName=_PRODUCT_NAMES.get(product, "未分类"),
            stage=stage,
            stageName=_STAGE_NAMES.get(stage, stage or "未分类"),
            acneed=_text(row.get("acneed_status")),
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
            amountCoverage=_div(past_amount_rows, past_rows) if past_rows else None,
            energyCoverage=_div(energy_rows, month_rows) if month_rows else None,
            pastRows=past_rows,
            pastAmountRows=past_amount_rows,
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
            productType=_text(row.get("product_type")) if _text(row.get("product_type")) in {"1", "2"} else "unknown",
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
        raise OpportunityV2Unavailable("商机 V2 核心取数失败且无可保留证据：" + labels)

    return dict(
        period=str(year),
        measurementDate=measured.isoformat(),
        targets=targets,
        productTypes=product_types,
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
        accountsComplete=query_status.get("客户") != "truncated",
        bidsComplete=query_status.get("投标") != "truncated",
        errors=errors,
        queryStatus=query_status,
        schema=schema,
        fetchedAt=time.time(),
        durationSeconds=round(time.monotonic() - started, 3),
    )


def _avg(values):
    found = [_number(value) for value in values]
    found = [value for value in found if value is not None and value >= 0]
    return sum(found) / len(found) if found else None


def _p0_cycle(opp, measured):
    created = _day(opp.get("createdAt"))
    if not created or created > measured:
        return None
    end = _day(opp.get("stage1End"))
    if opp.get("stage") == "11":
        end = measured
    if not end or end < created:
        return None
    return (end - created).days


def _p2_cycle(opp, measured):
    start = _day(opp.get("stage2End"))
    if not start:
        return None
    end = _day(opp.get("stage3End"))
    if not end and opp.get("stage") == "13":
        end = measured
    if not end or end < start:
        return None
    return (end - start).days


def _tier_label(tier):
    return {"strategic": "战略", "priority": "重点", "general": "一般"}.get(tier, "未分类")


def _level_for_gap(rate, thresholds=None):
    thresholds = thresholds or _thresholds({})
    if rate is None:
        return "中"
    if rate >= thresholds["gapRateHigh"]:
        return "高"
    if rate >= thresholds["gapRateMedium"]:
        return "中"
    return "低"


def _risk(code, name, level, title, description, metric_codes, evidence_ids, impact, objects):
    return dict(code=code, name=name, level=level, levelRank=_LEVEL_RANK.get(level, 9),
                title=title, description=description, metricCodes=list(dict.fromkeys(metric_codes)),
                evidenceIds=list(dict.fromkeys(evidence_ids))[:20], impact=impact, objects=list(objects))


def evaluate(data, config=None, measured=None):
    """Apply BR-A*/BR-C* rules to collected facts and return a card result."""
    config = config or load_config()
    thresholds = _thresholds(config)
    cycle_multiplier = _number((((config.get("overrides") or {}).get("dynamicCycle") or {}).get("multiplier"))) or 1.5
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

    # Formal-order amount is empty for most elapsed months.  Missing formal
    # amounts stay missing: the full-period forecast is disclosed separately
    # and never silently replaces the B02 rule input.
    if aggregate_ready:
        past_rows = int(sum(int(row.get("pastRows") or 0) for row in aggregates))
        past_amount_rows = int(sum(int(row.get("pastAmountRows") or 0) for row in aggregates))
    elif aggregate_mode:
        past_rows = past_amount_rows = 0
    else:
        past_rows = sum(int(opp.get("pastRows") or 0) for opp in opps)
        past_amount_rows = sum(int(opp.get("pastAmountRows") or 0) for opp in opps)
    amount_coverage = (_div(past_amount_rows, past_rows) if past_rows else
                       None if aggregate_mode and not aggregate_ready else 1.0)
    amount_basis = ("formal_order_actualized_incomplete"
                    if amount_coverage is not None and past_rows and amount_coverage < 0.80
                    else "formal_order_actualized")

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
    unsigned_ratio_amount = _div((unsigned_amount or 0) + max(gap_amount or 0, 0), target_amount) if target_amount else None
    unsigned_ratio_energy = _div((unsigned_energy or 0) + max(gap_energy or 0, 0), target_energy) if target_energy else None
    sign_progress_amount = _div(confirmed_amount, target_amount)
    sign_progress_energy = _div(confirmed_energy, target_energy)
    year_start = date(measured.year, 1, 1)
    year_end = date(measured.year, 12, 31)
    time_progress = ((measured - year_start).days + 1) / ((year_end - year_start).days + 1)
    lag_amount = (time_progress - sign_progress_amount) * 100 if sign_progress_amount is not None else None
    lag_energy = (time_progress - sign_progress_energy) * 100 if sign_progress_energy is not None else None
    quarter = (measured.month - 1) // 3 + 1
    quarter_window = _number((thresholds.get("quarterWindows") or {}).get(str(quarter)))

    focus = [opp for opp in unsigned if opp.get("tier") in {"strategic", "priority"}]
    if aggregate_ready:
        focus_predicate = lambda row: (row.get("contract") == "not_confirmed"
                                       and row.get("tier") in {"strategic", "priority"})
        focus_amount = aggregate_measure("amount", focus_predicate)
        focus_energy = aggregate_measure("energy", focus_predicate)
        focus_count = aggregate_count(focus_predicate)
        focus_has_strategic = bool(aggregate_rows(
            lambda row: row.get("contract") == "not_confirmed"
            and row.get("tier") == "strategic"))
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
        product_unsigned_ratio_amount = _div(
            (pending_amount or 0) + max(product_gap_amount or 0, 0), product_target_amount
        ) if product_target_amount else None
        product_unsigned_ratio_energy = _div(
            (pending_energy or 0) + max(product_gap_energy or 0, 0), product_target_energy
        ) if product_target_energy else None
        product_sign_progress_amount = _div(confirmed_product_amount, product_target_amount)
        product_sign_progress_energy = _div(confirmed_product_energy, product_target_energy)
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

    # Customer-level targets and forecasts.  Target rows stay row-level sums;
    # no unverified customer/product DISTINCT is applied.
    by_account = defaultdict(lambda: dict(target_amount=0.0, target_energy=0.0, forecast_amount=0.0,
                                          forecast_energy=0.0, opps=[], account_name="",
                                          tier="unknown", opportunity_count=0))
    for account_id, bucket in (target.get("byAccount") or {}).items():
        by_account[account_id]["target_amount"] += _number(bucket.get("amount")) or 0.0
        by_account[account_id]["target_energy"] += _number(bucket.get("energy")) or 0.0
    if aggregate_ready:
        for row in aggregates:
            bucket = by_account[row.get("accountId") or ""]
            bucket["forecast_amount"] += _number(row.get("amount")) or 0.0
            bucket["forecast_energy"] += _number(row.get("energy")) or 0.0
            bucket["opportunity_count"] += int(row.get("count") or 0)
            if not bucket["account_name"]:
                bucket["account_name"] = row.get("accountName") or ""
            if bucket["tier"] == "unknown":
                bucket["tier"] = row.get("tier") or "unknown"
    elif aggregate_mode:
        pass
    else:
        for opp in opps:
            bucket = by_account[opp.get("accountId") or ""]
            bucket["forecast_amount"] += _number(opp.get("forecastAmount")) or 0.0
            bucket["forecast_energy"] += _number(opp.get("forecastEnergy")) or 0.0
            bucket["opps"].append(opp)
            if not bucket["account_name"]:
                bucket["account_name"] = opp.get("accountName") or ""
            if bucket["tier"] == "unknown":
                bucket["tier"] = opp.get("tier") or "unknown"
    customer_gaps = []
    for account_id, bucket in by_account.items() if not (aggregate_mode and not aggregate_ready) else ():
        amount_gap = bucket["target_amount"] - bucket["forecast_amount"]
        energy_gap = bucket["target_energy"] - bucket["forecast_energy"]
        if amount_gap > 0 or energy_gap > 0:
            sample = bucket["opps"][0] if bucket["opps"] else {}
            customer_gaps.append(dict(accountId=account_id,
                                      accountName=bucket["account_name"] or sample.get("accountName", ""),
                                      tier=bucket["tier"] or sample.get("tier", "unknown"), amount=amount_gap,
                                      energy=energy_gap,
                                      count=bucket["opportunity_count"] or len(bucket["opps"])))

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
    never_opportunity = [account for account_id, account in strategic_accounts.items()
                         if complete_opportunity_scope and not all_by_account.get(account_id)]
    inactive_opportunity = [account for account_id, account in strategic_accounts.items()
                            if complete_opportunity_scope and all_by_account.get(account_id)
                            and not active_by_account.get(account_id)]
    no_opportunity = never_opportunity + inactive_opportunity
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

    stage_samples = defaultdict(lambda: defaultdict(list))
    for opp in opps:
        p0 = _p0_cycle(opp, measured) if detail_complete else None
        p2 = _p2_cycle(opp, measured) if detail_complete else None
        opp["p0Cycle"] = p0
        opp["p2Cycle"] = p2
        if detail_complete and p0 is not None and entered_this_year(opp, "P0"):
            stage_samples[opp.get("productType", "unknown")]["P0"].append(p0)
        if detail_complete and p2 is not None and entered_this_year(opp, "P2"):
            stage_samples[opp.get("productType", "unknown")]["P2"].append(p2)
    stage_average = {product: {stage: _avg(values) for stage, values in groups.items()}
                     for product, groups in stage_samples.items()}
    overall_p0 = (_avg([opp.get("p0Cycle") for opp in opps
                        if opp.get("p0Cycle") is not None and entered_this_year(opp, "P0")])
                  if detail_complete else None)
    overall_p2 = (_avg([opp.get("p2Cycle") for opp in opps
                        if opp.get("p2Cycle") is not None and entered_this_year(opp, "P2")])
                  if detail_complete else None)

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
    amount_basis_label = (
        "已历月份正式订单金额+当月及以后预测金额"
        if amount_basis == "formal_order_actualized"
        else "已历月份正式订单金额（覆盖不足，缺失部分不补预测）；全期间预测仅作参考"
    )
    f_b02_a = fact("B02-AMOUNT", "商机总预测（金额）", total_amount, "亿元",
                   amount_basis_label + "；月度预测有效且审核通过", source=forecast_source)
    f_b02_e = fact("B02-ENERGY", "商机总预测（电量）", total_energy, "GWh",
                   "预测订单数量（kWh 换算 GWh）；本方体 new_forcastpower 实库为空",
                   source=forecast_source)
    full_forecast_amount = (aggregate_measure("amountFull") if aggregate_ready else
                            None if aggregate_mode else
                            _sum(opp.get("forecastAmountFull") for opp in opps))
    f_b02_full = fact("B02-AMOUNT-FULL", "商机全期间预测（金额，仅参考）", full_forecast_amount, "亿元",
                      "同口径全期间预测金额；不替代正式金额口径，不参与风险规则")
    gap_source = target_source if target_source == forecast_source else f"derived（{target_source} / {forecast_source}）"
    f_r01_a = fact("R01-AMOUNT", "商机预测缺口（金额）", gap_amount, "亿元", "B01 − B02，金额单独计算", source=gap_source)
    f_r01_e = fact("R01-ENERGY", "商机预测缺口（电量）", gap_energy, "GWh", "B01 − B02，电量单独计算", source=gap_source)
    f_gap_rate_a = fact("R01-RATE-AMOUNT", "商机预测缺口率（金额）", gap_rate_amount * 100 if gap_rate_amount is not None else None, "%")
    f_gap_rate_e = fact("R01-RATE-ENERGY", "商机预测缺口率（电量）", gap_rate_energy * 100 if gap_rate_energy is not None else None, "%")
    f_r02_a = fact("R02-AMOUNT", "明确合同未确认商机预测（金额）", unsigned_amount, "亿元", "仅 new_contractconfirmation=0；状态未知单列，不混入待签")
    f_r02_e = fact("R02-ENERGY", "明确合同未确认商机预测（电量）", unsigned_energy, "GWh", "仅 new_contractconfirmation=0；状态未知单列，不混入待签")
    f_r02_unknown_a = fact("R02-UNKNOWN-AMOUNT", "合同状态未知商机预测（金额）", unknown_amount, "亿元", "new_contractconfirmation 为空或其他值；既不算已签也不算明确未签")
    f_r02_unknown_e = fact("R02-UNKNOWN-ENERGY", "合同状态未知商机预测（电量）", unknown_energy, "GWh", "new_contractconfirmation 为空或其他值；既不算已签也不算明确未签")
    f_r02_confirmed_a = fact("R02-CONFIRMED-AMOUNT", "已确认合同商机预测（金额）", confirmed_amount, "亿元", "仅 new_contractconfirmation=1")
    f_r02_confirmed_e = fact("R02-CONFIRMED-ENERGY", "已确认合同商机预测（电量）", confirmed_energy, "GWh", "仅 new_contractconfirmation=1")
    f_r03 = fact("R03-LAG", "已确认签订覆盖率落后时间进度（金额）", lag_amount, "百分点",
                 "已确认签订覆盖率 = 合同已确认商机预测金额 ÷ 目标金额；合同状态未知不计入已签或未签")
    f_r03_e = fact("R03-LAG-ENERGY", "已确认签订覆盖率落后时间进度（电量）", lag_energy, "百分点",
                   "已确认签订覆盖率 = 合同已确认商机预测电量 ÷ 目标电量；合同状态未知不计入已签或未签")
    f_r04_count = fact("R04-COUNT", "重点跟踪合同未确认商机数", focus_count, "条")
    f_r04_a = fact("R04-AMOUNT", "重点跟踪合同未确认预测（金额）", focus_amount, "亿元")
    f_r04_e = fact("R04-ENERGY", "重点跟踪合同未确认预测（电量）", focus_energy, "GWh")
    f_r05_a = fact("R05-AMOUNT", "电芯类合同未确认预测（金额）", products["1"]["pending_amount"], "亿元")
    f_r05_e = fact("R05-ENERGY", "电芯类合同未确认预测（电量）", products["1"]["pending_energy"], "GWh")
    f_r06_a = fact("R06-AMOUNT", "PACK 类合同未确认预测（金额）", products["2"]["pending_amount"], "亿元")
    f_r06_e = fact("R06-ENERGY", "PACK 类合同未确认预测（电量）", products["2"]["pending_energy"], "GWh")
    f_r08 = fact("R08", "客户预测缺口客户数", len(customer_gaps), "家", "客户目标 − 客户商机预测；金额或电量缺口大于 0")
    supplement_r09 = _number((supplement.get("R09") or {}).get("count")) if isinstance(supplement.get("R09"), dict) else None
    no_opportunity_count = len(no_opportunity)
    r09_source = "customer PostgreSQL · ded_public"
    if not accounts and supplement_r09 is not None:
        no_opportunity_count = max(0, int(supplement_r09))
        r09_source = supplement["R09"].get("source") or "AP 补充"
    f_r09 = fact("R09", "无商机战略客户数", no_opportunity_count, "家",
                 "战略客户名单内无任何商机；区分从未建立与历史有但当前无在推", source=r09_source)
    f_r10 = fact("R10", "有商机未投标战略客户数", len(no_bidding), "家", "全部商机均未进入投标；同名歧义不判未投标")
    f_r11 = fact("R11", "投标中商机数", len(in_progress_bids), "条", "已录入且尚未公布中标人")
    f_s03 = fact("S03", "投标平均周期", bid_average, "天", "中标公布时间或测量日 − 录入时间；全部有效投标")
    f_s03_p1 = fact("S03-P1", "电芯类投标平均周期", bid_average_by_product.get("1"), "天", "按关联商机产品类型拆分")
    f_s03_p2 = fact("S03-P2", "PACK 类投标平均周期", bid_average_by_product.get("2"), "天", "按关联商机产品类型拆分")
    f_p0 = fact("P0-01", "商机获取阶段平均周期", overall_p0, "天", "创建至阶段一结束或测量日；按电芯/PACK 分别计算")
    f_p2 = fact("P2-01", "方案推动阶段平均周期", overall_p2, "天", "阶段三结束或测量日 − 阶段二结束；按电芯/PACK 分别计算")
    f_rk10 = fact("P0-02", "商机获取阶段超期商机数", len(late_p0), "条", "单笔周期严格大于同阶段同产品动态均值 × 1.5")
    f_bid_amb = fact("BID-AMBIGUOUS", "投标同名歧义项目数", len(ambiguous_bid_names), "个", "同名多条投标记录；不据此判断未投标")
    f_cov = fact("COVERAGE-AMOUNT", "正式订单金额覆盖率", amount_coverage * 100 if amount_coverage is not None else None, "%", "已历月份正式订单金额非空的月度预测行占比")
    fact("B02-AMOUNT-BASIS", "金额预测口径", 0, "", f"amountBasis={amount_basis}")

    risks = []
    top_opps = lambda values, limit=8: [record(
        f"opp-v2:opp:{opp.get('id')}", customer=opp.get("accountName"), department=opp.get("department"),
        product=opp.get("productName"), status=f"{opp.get('stageName')}·合同{'已确认' if opp.get('contract') == 'confirmed' else '未确认' if opp.get('contract') == 'not_confirmed' else '状态未知'}",
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
        risks.append(_risk("RK01", "商机预测覆盖不足", level, "RK01 商机预测覆盖不足",
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
            parts.append(f"金额口径已确认签订覆盖率 {sign_progress_amount * 100:.1f}%、时间进度 {time_progress * 100:.1f}%，落后 {lag_amount:.1f} 个百分点。")
        if lag_energy is not None:
            parts.append(f"电量口径已确认签订覆盖率 {sign_progress_energy * 100:.1f}%，落后 {lag_energy:.1f} 个百分点。")
        if quarterly:
            parts.append(f"第 {quarter} 季度待签及缺口占比超过 {quarter_window * 100:.0f}% 窗口阈值。")
        evidence = [f_r03, f_r03_e, f_r02_a, f_r02_e, f_r02_unknown_a, f_r02_unknown_e,
                    f_r01_a, f_r01_e]
        risks.append(_risk("RK02", "签单进度滞后", level, "RK02 签单进度滞后（已确认签订覆盖率口径）",
                           "".join(parts), ["RK02", "R03", "R02", "R01"], evidence,
                           dict(amount=unsigned_amount, energy=unsigned_energy, count=None), []))

    # RK03
    if ((gap_amount is not None and gap_amount > 0) or (gap_energy is not None and gap_energy > 0)) and focus_count and ((focus_amount or 0) > 0 or (focus_energy or 0) > 0):
        level = "高" if focus_has_strategic else "中"
        parts = [f"战略及重点客户合同未确认商机 {focus_count} 条"]
        if focus_amount:
            parts.append(f"涉及预测金额 {focus_amount:.2f} 亿元")
        if focus_energy:
            parts.append(f"涉及预测电量 {focus_energy:.2f} GWh")
        evidence = [f_r04_count, f_r04_a, f_r04_e, f_r01_a, f_r01_e]
        risks.append(_risk("RK03", "重点跟踪合同未确认商机", level, "RK03 重点跟踪合同未确认商机",
                           "，".join(parts) + "；合同确认状态未完成。", ["RK03", "R04", "R01"], evidence,
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
            parts.append(f"合同未确认预测金额 {pending_amount:.2f} 亿元")
        if pending_energy:
            parts.append(f"合同未确认预测电量 {pending_energy:.2f} GWh")
        if under:
            parts.append("该类总预测低于同口径目标")
        product_lags = [value for value in (bucket.get("lag_amount"), bucket.get("lag_energy"))
                        if value is not None]
        if lagged and product_lags:
            parts.append(f"该类已确认签订覆盖率落后时间进度 {max(product_lags):.1f} 个百分点")
        evidence = [f_r05_a if key == "1" else f_r06_a, f_r05_e if key == "1" else f_r06_e]
        risks.append(_risk(code, "电芯类待签商机风险" if key == "1" else "PACK 类待签商机风险",
                           level, f"{code} {'电芯' if key == '1' else 'PACK'} 类待签商机风险",
                           "，".join(parts) + "；按合同确认口径判断。",
                           [code, "R05" if key == "1" else "R06", "B01", "B02"], evidence,
                           dict(amount=pending_amount, energy=pending_energy, count=bucket["pending_count"]), []))

    # RK06
    if customer_gaps:
        level = "高" if any(gap.get("tier") == "strategic" for gap in customer_gaps) else "中"
        amount_total = _sum(gap.get("amount") for gap in customer_gaps)
        energy_total = _sum(gap.get("energy") for gap in customer_gaps)
        parts = [f"{len(customer_gaps)} 家客户的目标高于商机预测"]
        if amount_total:
            parts.append(f"金额缺口合计 {amount_total:.2f} 亿元")
        if energy_total:
            parts.append(f"电量缺口合计 {energy_total:.2f} GWh")
        evidence = [f_r08]
        for gap in customer_gaps[:8]:
            account_id = gap.get("accountId")
            if account_id:
                evidence.append(record(f"opp-v2:account:{account_id}", customer=gap.get("accountName"),
                                       amount=_round(gap.get("amount"), 4),
                                       quantity=_round(gap.get("energy"), 4),
                                       unit="亿元/GWh", value=account_id, name=gap.get("accountName")))
        risks.append(_risk("RK06", "客户预测不足", level, "RK06 客户预测不足",
                           "，".join(parts) + "。", ["RK06", "R08"], evidence,
                           dict(amount=_round(amount_total, 4), energy=_round(energy_total, 4),
                                count=len(customer_gaps)), []))

    # RK07
    if no_opportunity or (not accounts and no_opportunity_count):
        evidence = [f_r09]
        for account in no_opportunity[:10]:
            evidence.append(record(f"opp-v2:account:{account.get('id')}", customer=account.get("name"),
                                   status="从未建立商机" if any(account is item for item in never_opportunity) else "历史有商机、当前无在推商机",
                                   value=account.get("id"), name=account.get("name")))
        description = (f"战略客户名单中有 {no_opportunity_count} 家无商机，其中 {len(never_opportunity)} 家从未建立商机、{len(inactive_opportunity)} 家历史有商机但当前无在推。"
                       if accounts else f"AP 补充口径显示有 {no_opportunity_count} 家无商机战略客户；客户明细未取得，不能归因。")
        risks.append(_risk("RK07", "战略客户待突破（无商机）", "高", "RK07 战略客户待突破（无商机）",
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
        risks.append(_risk("RK10", "商机获取阶段超期", level, "RK10 商机获取阶段超期",
                           f"{len(late_p0)} 条商机单笔周期超过同产品动态均值 1.5 倍；平均周期 {overall_p0:.1f} 天。",
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

    risks = sorted(unique.values(), key=lambda item: (
        item["levelRank"], -round(impact_ratio(item), 6), item["code"]))
    for risk in risks:
        risk["id"] = f"opp-v2:risk:{risk['code']}"
        risk["kind"] = "risk_fact"
        risk["impactScore"] = round(impact_ratio(risk), 6)

    # ---- causes -----------------------------------------------------------
    def acneed_unconfirmed(opp):
        # Empty/unknown approval is not evidence that customer demand is
        # unconfirmed.  Only explicit non-pass states may become RC01/RC07.
        return opp.get("acneed") in {"1", "2", "4", "5"}

    strategic_p0 = [opp for opp in unsigned if opp.get("tier") == "strategic" and opp.get("stage") == "11" and acneed_unconfirmed(opp)]
    p2_late = [opp for opp in unsigned if opp.get("stage") == "13" and opp in late_p2]
    p2_late = list({opp.get("id"): opp for opp in p2_late if opp.get("id")}.values())
    focus_ratio = _div(focus_amount, unsigned_amount) if unsigned_amount else None
    rest_amount = (unsigned_amount - (focus_amount or 0)) if unsigned_amount is not None else None
    rest_ratio = _div(rest_amount, unsigned_amount) if unsigned_amount else None
    rest_p0 = [opp for opp in unsigned if opp.get("tier") == "general" and opp.get("stage") == "11" and acneed_unconfirmed(opp)]
    product_pending_ratio = {}
    for key in ("1", "2"):
        bucket = products[key]
        product_pending_ratio[key] = _div(bucket.get("pending_amount"), bucket.get("total_amount")) if bucket.get("total_amount") else None

    candidates = {}
    if strategic_p0:
        amount = _sum(opp.get("forecastAmount") for opp in strategic_p0)
        energy = _sum(opp.get("forecastEnergy") for opp in strategic_p0)
        candidates["RC01"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="战略客户需求确认未落实",
            description=f"{len(strategic_p0)} 条战略客户 P0 商机合同未确认且客户需求审核未通过，涉及" +
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
        parts = [f"{_PRODUCT_NAMES.get(key, key)} 待签占比 {ratio * 100:.1f}%" for key, ratio in concentration.items()]
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
        description=f"重点跟踪合同未确认商机占全部合同未确认预测 {focus_ratio * 100:.1f}%，低于 {thresholds['focusTrackingRatio'] * 100:.0f}% 阈值。",
            evidence=[f_r04_a, f_r04_e, f_r02_a, f_r02_e],
            risks={"RK01", "RK02"} & {risk["code"] for risk in risks},
        )
    if rest_ratio is not None and rest_ratio >= thresholds["otherPendingRatio"] and rest_p0:
        amount = _sum(opp.get("forecastAmount") for opp in rest_p0)
        candidates["RC07"] = dict(
            kind="verified", status="supported", stage="opportunity",
            title="其余商机需求未确认",
            description=f"一般客户合同未确认预测占比 {rest_ratio * 100:.1f}%，其中 {len(rest_p0)} 条 P0 商机需求审核未通过" +
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
            missingEvidence=[],
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
    advice_codes = [code for code in advice_codes if code in (config.get("advice") or {})][:4]
    if not advice_codes and displayed:
        advice_codes = ["DS06"] if "DS06" in (config.get("advice") or {}) else []

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
        recommendations.append(dict(
            id=f"opp-v2:advice:{code}", adviceCode=code,
            actionType="remediation" if any(cause.get("kind") == "verified" and cause.get("status") == "supported" for cause in linked_causes) else "investigation",
            causeIds=[cause["id"] for cause in linked_causes], evidenceIds=evidence_ids[:20],
            action=action[:64], ownerRole=(template.get("owner") or "待确认")[:40],
            deadlineDays=_deadline_days(template.get("deadline")), acceptance=_acceptance(code)[:180],
            detail=(template.get("measure") or "")[:600], ownerConfirmed=False, deadlineConfirmed=False,
            riskCodes=risk_codes, linkedRiskCodes=linked_risk_codes or risk_codes,
        ))
    if not recommendations and displayed:
        risk = displayed[0]
        recommendations.append(dict(
            id="opp-v2:advice:investigate", adviceCode="INVESTIGATE", actionType="investigation",
            causeIds=[], evidenceIds=risk["evidenceIds"][:1], action=f"核查{risk['name']}的影响客户与预测口径"[:64],
            ownerRole="销售运营", deadlineDays=10, acceptance="形成受影响客户、商机与预测量的可核对清单",
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
    for risk in displayed[:2]:
        summary_parts.append(f"{risk['code']} {risk['name']}（{risk['description']}）")
    summary = "商机获取 V2 规则核验：" + "；".join(summary_parts) if summary_parts else "商机获取 V2 规则核验：本期未触发风险规则，合同未确认与预测口径仍按证据保留。"
    summary = re.sub(r"\s+", " ", summary)[:240]

    if data.get("errors"):
        limitations.append("部分可选查询未返回：" + "、".join(sorted({item.get('stage') or item.get('code') or '未知' for item in data["errors"]})))
    if aggregate_mode and not aggregate_ready:
        limitations.append(
            "商机明细达到行数上限，全量聚合未返回；截断明细不参与金额、电量、合同、产品、客户和风险规则计算。")
    elif not detail_complete:
        limitations.append(
            "商机月度明细达到行数上限；明细仅用于展示，金额、电量、合同、产品、客户规则采用全量聚合；逐条周期和项目进展规则未判定。")
    if not all_opps_complete:
        limitations.append(
            "全部商机明细达到行数上限；战略客户无商机、未投标等逐客户判断未执行，避免把截断样本当成全量。")
    if not bids_complete:
        limitations.append("投标明细达到行数上限；投标周期和投标中项目相关规则未判定。")
    limitations.extend([
        "合同签订按 new_contractconfirmation 判断；签订日期字段实库为空，不能用日期推断。",
        "签单进度按已确认签订覆盖率计算（合同已确认商机预测 ÷ 目标）；合同状态未知不计入已签或未签，也不单独触发进度滞后。",
        "目标表按行求和，未按客户或产品去重；目标表缺少经验证的业务唯一键。",
        "预测电量使用 new_orderforecast_qty（kWh）换算 GWh；本体登记的 new_forcastpower 实库为空。",
        "项目阶段按 11~15 映射 P0~P4；其他枚举不推断。投标关联仅使用去首尾空格后的精确名称，同名歧义不判未投标。",
        "RC04 产品部销售缺口需跨发货环节实际销售，本次不把不可得数据推成原因。",
        "动态均值只取本年度进入该阶段、同产品类型、截至测量日的有效商机；缺进入时间或时间倒置的记录已排除。",
        "建议中的责任角色与期限为模板草稿，须人工确认后才能下发任务令。",
    ])
    if unknown_contract_count:
        limitations.append(
            f"{unknown_contract_count} 条商机合同状态未知，涉及预测金额 {unknown_amount or 0:.2f} 亿元、"
            f"电量 {unknown_energy or 0:.2f} GWh；未知单列，既不计入明确未确认，也不视为已签。")
    if (total_amount is not None and amount_coverage is not None and amount_coverage < 0.8):
        limitations.append(
            f"正式订单金额覆盖率 {amount_coverage * 100:.1f}%，缺失的正式金额未补成预测金额；"
            "全期间预测金额仅作参考，不替代 B02 参与规则。")

    result = dict(
        summary=summary,
        findings=findings,
        causes=[dict(
            id=cause["id"], causeCode=cause["causeCode"], kind=cause["kind"],
            title=cause["title"], description=cause["description"], stage=cause["stage"],
            status=cause["status"], findingIds=cause["findingIds"], evidenceIds=cause["evidenceIds"],
            riskCodes=[code for code in sorted(candidates[cause["causeCode"]]["risks"])
                       if code in displayed_code_set],
            linkedRiskCodes=sorted(candidates[cause["causeCode"]]["risks"]),
            missingEvidence=[],
        ) for cause in cause_items],
        analysisDimensions=dimensions,
        recommendations=recommendations,
        limitations=list(dict.fromkeys(limitations))[:10],
        riskTotalCount=len(risks),
        riskCodes=[risk["code"] for risk in risks],
        riskLevels={risk["code"]: risk["level"] for risk in risks},
        ontologyVersion=config.get("version"),
        sourceConfigDigest=config_digest(),
        measurementDate=data.get("measurementDate"),
    )
    return dict(
        result=result,
        evidence=dict(
            facts=list(evidence_facts.values()),
            records=records,
            evidence=evidence_refs,
            limitations=list(dict.fromkeys(limitations))[:10],
            periods=[data.get("period")],
            dataAsOf=data.get("measurementDate"),
        ),
        metrics=dict(
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
            R08=dict(count=len(customer_gaps)),
            R09=dict(count=no_opportunity_count, never=len(never_opportunity), inactive=len(inactive_opportunity)),
            R10=dict(count=len(no_bidding)),
            R11=dict(count=len(in_progress_bids)),
            S03=bid_average, P0=overall_p0, P2=overall_p2,
            bidAmbiguous=len(ambiguous_bid_names),
        ),
        risks=risks,
        causes=cause_items,
        recommendations=recommendations,
        textSamples=progress_samples if "RC02" in chosen else [],
    )


def default_text_interpreter(payload):
    """Use the deployment model only to explain supplied progress text.

    The model receives the already-triggered risks, selected causes, advice
    codes and progress snippets.  It cannot choose new tables, risks, causes or
    actions.  A failed/invalid response is handled by the caller and never
    blocks the deterministic rule-backed card.
    """
    from ..llm import provider
    from ..llm.registry import get_default_model_key
    from ..llm.runtime_config import request_config

    system_prompt = (
        "你是证据约束的经营分析助手。只能解释输入中的项目进展文本，不得补充输入之外的事实、"
        "不得新增风险、原因或建议代码，不得猜测数字。只返回 JSON："
        '{"causeDescriptions":{"RC02":"不超过160字"},'
        '"causeEvidence":{"RC02":["progressSamples中的evidenceId"]},'
        '"adviceActions":{"DSxx":"不超过64字"}}。'
        "原因描述必须说明文本中已出现的商务或技术卡点，并保留‘需人工复核’；建议只可改写给定建议代码的动作。"
        "每条原因必须引用至少一条 progressSamples.evidenceId，不得引用输入之外的编号。"
        "不得使用‘逾期未完成’表述。"
    )
    events = []
    key = get_default_model_key()
    with request_config(thinking=False, request_timeout=max(15, min(
            int(os.environ.get("COCKPIT_OPPORTUNITY_V2_MODEL_TIMEOUT_SECONDS", "60")), 120))):
        for event in provider.stream_message(
            [dict(role="user", content=json.dumps(payload, ensure_ascii=False))],
            system_prompt, None, key, max_tokens=1200, temperature=0, thinking=False,
        ):
            events.append(event)
    errors = [event.get("error", "") for event in events if event.get("type") == "error"]
    if errors:
        raise RuntimeError(errors[-1])
    text = "".join(event.get("text", "") for event in events if event.get("type") == "text_delta").strip()
    if not text or not any(event.get("type") == "message_end" for event in events):
        raise RuntimeError("模型未返回完整文本")
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = fenced.group(1) if fenced else text[text.find("{"):text.rfind("}") + 1]
    if not raw:
        raise RuntimeError("模型未返回 JSON")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("模型 JSON 不是对象")
    return value


def _model_numbers(value):
    return set(re.findall(r"(?<!\d)\d+(?:\.\d+)?(?!\d)", json.dumps(value, ensure_ascii=False, default=str)))


def apply_text_interpretation(evaluated, interpreter=None):
    """Validate and apply model wording without allowing model-created facts."""
    samples = evaluated.get("textSamples") or []
    selected_causes = [cause for cause in evaluated.get("causes") or [] if cause.get("causeCode") == "RC02"]
    selected_advice = {item.get("adviceCode"): item for item in evaluated.get("result", {}).get("recommendations") or []
                       if item.get("adviceCode")}
    if not samples or not selected_causes or not interpreter:
        return dict(status="skipped", error="")
    payload = dict(
        risks=[dict(code=code, name=next((risk.get("name") for risk in evaluated.get("risks") or []
                                          if risk.get("code") == code), ""))
               for code in evaluated.get("result", {}).get("riskCodes") or []],
        causes=[dict(code=cause["causeCode"], title=cause["title"], description=cause["description"])
                for cause in selected_causes],
        advice=[dict(code=code, action=item.get("action")) for code, item in selected_advice.items()],
        progressSamples=samples[:6],
    )
    allowed_numbers = _model_numbers(payload)
    try:
        value = interpreter(payload)
        if not isinstance(value, dict):
            raise ValueError("模型结果不是对象")
        descriptions = value.get("causeDescriptions") or {}
        evidence = value.get("causeEvidence") or {}
        actions = value.get("adviceActions") or {}
        if not isinstance(descriptions, dict) or not isinstance(evidence, dict) or not isinstance(actions, dict):
            raise ValueError("模型结果字段类型错误")
        cause_by_code = {cause["causeCode"]: cause for cause in selected_causes}
        allowed_evidence = {sample.get("evidenceId") for sample in samples if sample.get("evidenceId")}
        applied_causes, applied_actions = [], []
        for code, description in descriptions.items():
            description = _text(description)
            cited = evidence.get(code) or []
            if (code not in cause_by_code or not description or len(description) > 160
                    or "逾期未完成" in description
                    or not isinstance(cited, list) or not cited
                    or not {_text(item) for item in cited} <= allowed_evidence
                    or not _model_numbers(description) <= allowed_numbers):
                continue
            cause_id = cause_by_code[code]["id"]
            for item in evaluated["result"].get("causes") or []:
                if item.get("id") == cause_id:
                    item["description"] = description
            for item in evaluated["result"].get("analysisDimensions") or []:
                if item.get("id") == cause_id:
                    item["description"] = description[:240]
            applied_causes.append(code)
        for code, action in actions.items():
            action = _text(action)
            if (code not in selected_advice or not action or len(action) > 64
                    or "逾期未完成" in action
                    or not _model_numbers(action) <= allowed_numbers):
                continue
            selected_advice[code]["action"] = action
            applied_actions.append(code)
        return dict(status="completed", error="", causes=applied_causes, advice=applied_actions)
    except Exception as exc:  # noqa: BLE001 - model enrichment is optional
        return dict(status="failed", error=type(exc).__name__)


def _deadline_days(value):
    text = _text(value)
    match = re.search(r"(\d+)", text)
    if match:
        return max(1, min(int(match.group(1)), 365))
    return 30


def _acceptance(code):
    return {
        "DS01": "形成战略客户、无商机/未投标分组、责任人与突破时间表的可核对清单",
        "DS02": "逐客户形成商务与技术前置条件关闭清单，并记录投标计划日期",
        "DS03": "逐客户形成商机建立计划、目标产品部与需求调研完成时间",
        "DS04": "按电芯与 PACK 分别形成合同未确认商机转化清单和责任人",
        "DS05": "形成技术卡点、责任资源与排期确认记录，逐项关闭",
        "DS06": "形成月度经营对账记录，确认推进率与达成率口径一致",
        "DS07": "形成重点跟踪纳管清单，核对重点跟踪占合同未确认预测比例",
        "DS08": "逐条形成需求确认记录与预计签约时间",
    }.get(code, "形成可核对的对象、数值、责任人与完成时间记录")


def _advice_action(code, template, values):
    strategic = values.get("strategic_count") or 0
    if code == "DS01":
        return f"针对 {strategic} 家战略客户制定突破计划，分别跟进无商机与未投标客户"
    if code == "DS02":
        return f"推动 {values.get('no_bidding') or 0} 家战略客户进入投标并关闭前置条件"
    if code == "DS03":
        return f"对 {values.get('no_opportunity') or 0} 家无商机战略客户限期建立商机"
    if code == "DS04":
        return "对电芯与 PACK 合同未确认商机分别制定转化计划，优先保障缺口最大的产品部"
    if code == "DS05":
        return f"对 {values.get('bid_late') or 0} 项投标超期及 {values.get('late_p2') or 0} 条方案推动超期项目优先排资源"
    if code == "DS06":
        return "将战略客户商机推进率与产品部达成率纳入月度经营对账"
    if code == "DS07":
        ratio = values.get("focus_ratio")
        suffix = f"（当前 {ratio * 100:.1f}%）" if ratio is not None else ""
        target = round((values.get("focus_threshold") or 0.70) * 100)
        return f"将战略、重点客户合同未确认商机纳入重点跟踪，使占比达到 {target}%{suffix}"
    if code == "DS08":
        return f"对 {values.get('rest_p0') or 0} 条一般客户 P0 需求未确认商机逐条确认需求"
    return (template.get("measure") or "")[:64]


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
    if not data.get("accounts") and (data.get("queryStatus") or {}).get("客户") in {"failed", "truncated"}:
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


def _empty_collected(period, measured, error):
    return dict(
        period=str(period), measurementDate=measured.isoformat(),
        targets=dict(amount=None, energy=None, rows=0, amountCells=0, energyCells=0,
                     byProduct={}, byAccount={}),
        productTypes={}, opportunities=[], allOpportunities=[], accounts=[],
        bids=[], progress={}, departments={},
        errors=[dict(stage="database", code=type(error).__name__)],
        queryStatus={"database": "failed", "商机预测": "failed", "客户": "failed"},
        schema="", fetchedAt=time.time(), durationSeconds=0.0,
    )


def build_card(period, database=None, measurement_date=None, config=None, text_interpreter=None,
               supplement=None, progress=None):
    """Build one complete ``opportunity-risk`` publication payload."""
    _report_progress(progress, "ontology", message="读取本体与规则配置")
    config = config or load_config()
    started = time.monotonic()
    measured = _measurement_context(period, measurement_date)
    collected_error = None
    _report_progress(progress, "fetching", message="查询数据库", completed=0, total=9)
    try:
        data = collect(period, measured, database=database, config=config, progress=progress)
    except OpportunityV2Unavailable as exc:
        if supplement is None:
            raise
        collected_error = exc
        data = _empty_collected(period, measured, exc)
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
    if collected_error is not None and not data.get("supplement"):
        raise collected_error
    _report_progress(progress, "rules", message="计算指标并判断风险规则")
    evaluated = evaluate(data, config, measured)
    _report_progress(progress, "analysing", message="归纳有文本证据的原因与建议")
    model_status = apply_text_interpretation(evaluated, text_interpreter)
    fetched_at = time.time()
    result = evaluated["result"]
    result["cardContract"] = "cockpit-cards-v1"
    result["engine"] = "opportunity-v2-rules"
    if model_status.get("status") == "failed":
        result["limitations"] = list(dict.fromkeys((result.get("limitations") or []) + [
            "项目进展文本的模型归纳未完成；已保留规则风险与有逐条文本证据的待复核原因。"
        ]))[:10]
    if collected_error is not None:
        result["limitations"] = list(dict.fromkeys((result.get("limitations") or []) + [
            "数据库核心取数未完成，卡片仅保留 AP 可补充的聚合指标；项目、客户和投标明细未参与判定。"
        ]))[:10]
    if data.get("supplement"):
        result["limitations"] = list(dict.fromkeys((result.get("limitations") or []) + [
            "部分目标/预测指标来自 AP 补充，已在对应指标来源中标明；明细级风险不据 AP 聚合值推导。"
        ]))[:10]
    if supplement_errors:
        result["limitations"] = list(dict.fromkeys((result.get("limitations") or []) + [
            "AP 补充未全部成功：" + "、".join(sorted(set(supplement_errors))[:4])
        ]))[:10]
    _report_progress(progress, "publishing", message="校验并发布卡片")
    item = dict(
        id=uuid.uuid4().hex,
        status="limited" if (data.get("errors") or missing) else "completed",
        context=dict(
            stage="opportunity", slotId=SLOT_ID, period=str(period), id=1,
            dataFingerprint=hashlib.sha256(json.dumps(dict(
                period=str(period), measurementDate=measured.isoformat(),
                metrics=evaluated["metrics"], riskCodes=result["riskCodes"]), ensure_ascii=False,
                sort_keys=True, default=str).encode()).hexdigest(),
            ontologyVersion=config.get("version"), source="opportunity-v2",
            measurementDate=measured.isoformat(),
        ),
        result=result,
        evidence=evaluated["evidence"],
        metrics=evaluated["metrics"],
        risks=evaluated["risks"],
        execution=dict(
            engine="opportunity-v2-rules", durationSeconds=round(time.monotonic() - started, 3),
            queryDurationSeconds=data.get("durationSeconds"), fetchedAt=fetched_at,
            source="customer PostgreSQL", measurementDate=measured.isoformat(),
            rulesVersion=config.get("version"), configDigest=config_digest(),
            riskCount=len(evaluated["risks"]), errorCount=len(data.get("errors") or []),
            modelStatus=model_status, supplementMissing=missing,
            supplementErrors=sorted(set(supplement_errors))[:8],
        ),
        updatedAt=fetched_at,
    )
    return item


__all__ = [
    "SLOT_ID", "RULES_VERSION", "OpportunityV2Unavailable", "load_config",
    "config_version", "config_digest", "collect", "evaluate", "build_card",
    "apply_text_interpretation", "default_text_interpreter", "default_ap_supplement",
]
