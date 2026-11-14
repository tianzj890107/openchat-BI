"""销售额／出货量共同问题分析 card: indicator → problem → cause → advice.

The card is problem driven, not risk driven.  Problems are either metric
anomalies (an indicator against its target or threshold) or data problems
(the evidence itself failed, is empty or disagrees with itself).

Everything is read from ``assets/sales-shipment/config.json``, built from the
card's ontology workbook: every metric's executable SQL, every problem and
cause condition with its thresholds, the links and the advice.  The run is
rule first, like the 商机获取 card: rule functions settle what the data can
settle, each remaining item goes to the model on its own, and a problem that
no ontology cause explains gets one inference call.  A query that fails is
reported as a data problem instead of failing the card; only a card with no
usable query at all fails.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from . import opportunity_v2 as v2
from .opportunity_judgement import ONTOLOGY_RULES, judge_card, link_queries, make_item_judge

SLOT_ID = "sales-shipment-issues"
STAGE = "combined"
RULES_VERSION = "sales-shipment-rules-1"
CONFIG_PATH = Path(__file__).resolve().parent / "assets" / "sales-shipment" / "config.json"
CORE_METRICS = ("B01", "B02", "B03", "B04")
STRATEGIC_LEVELS = {"1": "战略大客户", "2": "重要大客户"}
OVERDUE_HANDLING = {"overdue_uncompleted": "逾期未完成", "overdue_completed": "逾期完成"}
_CACHE: dict = {}


class SalesShipmentUnavailable(RuntimeError):
    """The card cannot be built at all (no database or no usable query)."""


# ---------------------------------------------------------------- config
def load_config():
    stamp = CONFIG_PATH.stat().st_mtime_ns
    cached = _CACHE.get("config")
    if cached and cached[0] == stamp:
        return cached[1]
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if config.get("version") != RULES_VERSION:
        raise SalesShipmentUnavailable("销售额／出货量共同问题分析运行配置版本不匹配")
    for code, link in (config.get("links") or {}).items():
        if code not in config["issues"]:
            raise SalesShipmentUnavailable(f"链路引用未知问题：{code}")
        if not set(link.get("causes") or []) <= set(config["causes"]):
            raise SalesShipmentUnavailable(f"链路引用未知根因：{code}")
    _CACHE["config"] = (stamp, config)
    return config


def config_digest():
    return hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()


# ---------------------------------------------------------------- model roles
ROLE_PROMPT = (
    "你是储能业务销售运营分析师，请用客观、简洁的经营汇报用语：问题说明影响对象、"
    "实际值与目标或阈值的差距，数据问题说明受影响的指标与数据来源；根因仅在证据充分时表述为已确认、"
    "证据不足时标注「待核实」；建议写清责任角色、具体措施和复检指标。"
)
INFER_PROMPT = (
    "销售额与出货量共同问题的根因推理。下面这条问题（risk 字段，可能是指标异常或数据问题）已经成立，"
    "但本体中与它关联的根因规则都没有命中。请只依据 risk（问题的本体定义、判定规则与判定数据）、"
    "ontologyCauses（各本体候选根因的定义、判定规则、判定结果和原因）和 data.metrics（只含本问题及其"
    "候选根因涉及的指标，附本体口径与本轮取值）推理最可能导致该问题的根因。" + ONTOLOGY_RULES +
    "不要重复已判定未命中的本体根因，也不要把它换一种说法重新提出，除非 data 中有相反证据。"
    "最多给出 3 条，按可能性从高到低排列；数据不足以推理时 causes 返回空数组，并在 note 中写明缺少什么。"
    "推理出的根因都未经规则确认，description 以「待核实」开头。"
    '只返回 JSON：{"causes": [{"title": "不超过20字的根因名称", '
    '"description": "不超过160字的推理依据，引用 data 中的具体数值", '
    '"dataGaps": "需要补充核实的数据，没有则为空字符串"}], "note": ""}，不要输出其他内容。'
)


def role_prompt():
    """The card's system role; COCKPIT_SALES_SHIPMENT_ROLE_PROMPT replaces it when set."""
    override = os.environ.get("COCKPIT_SALES_SHIPMENT_ROLE_PROMPT", "").strip()
    return override or ROLE_PROMPT


def summary_role():
    """Role for the section summaries: the card's ``risks`` are its problems."""
    return (role_prompt() + "本卡片输入中的 risks 条目是“问题”（指标异常或数据问题），"
            "总结时一律称“问题”，不要称“风险”。")


item_judge = make_item_judge(role_prompt, INFER_PROMPT)


# ---------------------------------------------------------------- data fetching
def _env_int(name, default, low, high):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(low, min(value, high))


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def collect(period, measured, database=None, config=None, progress=None, diagnostic_reporter=None):
    """Run every ontology metric SQL of the card in one read-only snapshot.

    A failed, timed-out or truncated statement is kept as a query result with
    its status; the problems layer turns it into data problem DQ01.
    """
    config = config or load_config()
    year = int(str(period)[:4])
    database = database or v2._database()
    if not getattr(database, "available", False):
        reason = v2._text(getattr(database, "unavailable_reason", lambda: "")()) or "数据库不可用"
        error = SalesShipmentUnavailable(reason)
        error.phase, error.code, error.diagnostic_message = "database_connect", "DATABASE_UNAVAILABLE", reason
        raise error
    schema = getattr(database.config, "schema", "ded_public") or "ded_public"
    timeout_ms = _env_int("COCKPIT_SALES_SHIPMENT_QUERY_TIMEOUT_MS", 60000, 1000, 120000)
    budget = _env_int("COCKPIT_SALES_SHIPMENT_FETCH_BUDGET_SECONDS", 300, 10, 900)
    workers = _env_int("COCKPIT_SALES_SHIPMENT_DB_WORKERS", 3, 1, 6)
    db_config = getattr(database, "config", None)
    source = dict(source="customer PostgreSQL", database=v2._text(getattr(db_config, "database", "")),
                  schema=v2._text(schema), host=v2._text(getattr(db_config, "host", "")),
                  port=getattr(db_config, "port", None))
    metrics = config["metrics"]
    shared, results, catalog, errors = {}, {}, [], []
    for code, metric in metrics.items():
        if metric.get("derived"):
            continue
        sql = v2._ontology_metric_sql(config, code, year, measured, schema)
        if not sql:
            results[code] = dict(status="unbound", rows=[], error=dict(code="SQL_UNBOUND",
                                 message="调用SQL无法绑定统计期间或观察时点"))
            continue
        shared.setdefault(sql, []).append(code)
    # Metrics taken from the same dashboard combination query share one
    # statement: it runs once and its row feeds every metric it carries.
    owners = {codes[0]: codes for codes in shared.values()}
    specs = [(codes[0], sql) for sql, codes in shared.items()]
    total = len(specs)
    done = 0
    started = time.monotonic()
    deadline = started + budget

    def record(code, sql, status, rows, duration, error, meta):
        nonlocal done
        done += 1
        codes = owners.get(code, [code])
        row_meta = v2._query_result_meta(rows)
        entry = dict(
            executionId=uuid.uuid4().hex, label="、".join(f"{c} {metrics[c]['name']}" for c in codes),
            metricCodes=list(codes),
            sql=sql, params=[], status=status, durationSeconds=round(duration, 3),
            durationMs=int(round(duration * 1000)), startedAt=meta.get("startedAt", ""),
            finishedAt=meta.get("finishedAt", ""), rowCount=len(rows), truncated=status == "truncated",
            resultHash=row_meta["resultHash"], columns=row_meta["columns"], sampleRows=row_meta["sampleRows"],
            sampleRowCount=row_meta["sampleRowCount"], sampleTruncated=row_meta["sampleTruncated"],
            sampleLimit=row_meta["sampleLimit"],
            aggregation="；".join(f"{c}：{metrics[c].get('definition', '')}" for c in codes), **source)
        if error:
            entry["error"] = {key: error.get(key) for key in ("code", "upstreamCode", "message") if error.get(key)}
            if diagnostic_reporter is not None:
                try:
                    saved = diagnostic_reporter(dict(error, query="、".join(codes)))
                    if isinstance(saved, dict) and saved.get("diagnosticId"):
                        entry["error"]["diagnosticId"] = saved["diagnosticId"]
                except Exception:  # noqa: BLE001 - diagnostics never fail the card
                    pass
            errors.append(dict(stage="、".join(codes), code=error.get("code") or "QUERY_FAILED",
                               message=(error.get("message") or "")[:300]))
        catalog.append(entry)
        for each in codes:
            results[each] = dict(status=status, rows=rows, error=error)
        v2._report_progress(progress, "fetching", message=f"查询数据库 {done}/{total}", query=entry["label"],
                            completed=done, total=total, queryStatus=status,
                            queryDurationSeconds=round(duration, 3))

    def run_one(reader, spec):
        code, sql = spec
        begin, clock = _now_iso(), time.monotonic()
        try:
            result = reader.run(sql, [], timeout_ms=timeout_ms)
            rows = [dict(row) for row in result.rows]
            truncated = bool(getattr(result, "truncated", False))
            error = (dict(phase="database_query", query=code, code="ROW_LIMIT", message="row limit reached")
                     if truncated else None)
            return code, sql, "truncated" if truncated else "ok", rows, time.monotonic() - clock, error, \
                dict(startedAt=begin, finishedAt=_now_iso())
        except Exception as exc:  # noqa: BLE001 - one query failing is a data problem, not a crash
            duration = time.monotonic() - clock
            return code, sql, "failed", [], duration, v2._query_failure(exc, code, duration), \
                dict(startedAt=begin, finishedAt=_now_iso())

    v2._report_progress(progress, "fetching", message=f"查询数据库 0/{total}", completed=0, total=total)
    with v2._reader_group(database, workers=workers) as (readers, parallel):
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
                                          thread_name_prefix="cockpit-sales-shipment-db")
            pending = {executor.submit(work, spec): spec for spec in specs}
            try:
                while pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    finished, _ = wait(set(pending), timeout=remaining, return_when=FIRST_COMPLETED)
                    for future in finished:
                        spec = pending.pop(future)
                        try:
                            record(*future.result())
                        except Exception as exc:  # noqa: BLE001 - worker crash
                            record(spec[0], spec[1], "failed", [], 0.0, v2._query_failure(exc, spec[0], 0.0), {})
                if pending:
                    for future in pending:
                        future.cancel()
                    for reader in readers:
                        cancel = getattr(reader, "cancel", None)
                        if callable(cancel):
                            cancel()
                    for spec in pending.values():
                        record(spec[0], spec[1], "timeout", [], 0.0,
                               dict(phase="database_query", query=spec[0], code="TIMEOUT",
                                    message="database fetch budget exhausted"), {})
            finally:
                executor.shutdown(wait=True, cancel_futures=True)
        else:
            for spec in specs:
                if time.monotonic() >= deadline:
                    record(spec[0], spec[1], "timeout", [], 0.0,
                           dict(phase="database_query", query=spec[0], code="TIMEOUT",
                                message="database fetch budget exhausted"), {})
                    continue
                record(*run_one(readers[0], spec))
    order = {code: index for index, code in enumerate(metrics)}
    catalog.sort(key=lambda entry: order.get(entry["metricCodes"][0], 999))
    return dict(period=str(period), measurementDate=measured.isoformat(), results=results,
                queryCatalog=catalog, errors=errors, durationSeconds=round(time.monotonic() - started, 3),
                queryTimeoutMs=timeout_ms, fetchBudgetSeconds=budget)


# ---------------------------------------------------------------- metric values
def _dim_columns(metric):
    """Columns of a grouped result (from the SQL's dimension aliases)."""
    return [f"YWLN_{code}" for code in metric.get("groupBy") or []]


def metric_values(data, config):
    """Read each metric's value (and groups) from the query results; derive the rest."""
    values = {}
    for code, metric in config["metrics"].items():
        if metric.get("derived"):
            continue
        result = (data.get("results") or {}).get(code) or dict(status="missing", rows=[])
        column = metric["resultColumn"]
        dims = _dim_columns(metric)
        rows = result.get("rows") or []
        entry = dict(code=code, name=metric["name"], unit=metric["unit"], status=result.get("status"), value=None)
        if result.get("status") == "ok" and rows:
            if dims:
                groups = [dict(dims={col.replace("YWLN_", ""): v2._text(row.get(col)) for col in dims},
                               value=v2._number(row.get(column))) for row in rows]
                entry["groups"] = groups
                numbers = [group["value"] for group in groups if group["value"] is not None]
                if code == "S12":
                    entry["value"] = max(numbers) if numbers else None
                    entry["count"] = sum(1 for number in numbers if number > 0)
                elif metric["unit"] in {"%", "比值", "天"}:
                    entry["value"] = None
                else:
                    entry["value"] = round(sum(numbers), 6) if numbers else None
            else:
                entry["value"] = v2._number(rows[0].get(column))
        values[code] = entry

    def num(code):
        return (values.get(code) or {}).get("value")

    def derive(code, value, inputs):
        values[code] = dict(code=code, name=config["metrics"][code]["name"], unit=config["metrics"][code]["unit"],
                            status="derived", value=value, inputs=inputs)

    r01, r02 = num("R01"), num("R02")
    derive("R03", round((r01 - r02) * 100, 4) if r01 is not None and r02 is not None else None, ["R01", "R02"])
    b01, b02, b03, b04 = (num(code) for code in CORE_METRICS)
    derive("R09", round(b02 / b04 * 0.1, 6) if b02 is not None and b04 else None, ["B02", "B04"])
    derive("R10", round(b01 / b03 * 0.1, 6) if b01 is not None and b03 else None, ["B01", "B03"])
    remaining_amount = (b01 - b02) if b01 is not None and b02 is not None else None
    remaining_energy = (b03 - b04) if b03 is not None and b04 is not None else None
    s03, s04 = num("S03"), num("S04")
    coverage = dict(
        amount=round(s04 / remaining_amount, 6) if s04 is not None and remaining_amount and remaining_amount > 0 else None,
        energy=round(s03 / remaining_energy, 6) if s03 is not None and remaining_energy and remaining_energy > 0 else None,
        remainingAmount=remaining_amount, remainingEnergy=remaining_energy)
    derive("C09", min([v for v in (coverage["amount"], coverage["energy"]) if v is not None], default=None),
           ["S04", "B01", "B02", "S03", "B03", "B04"])
    values["C09"].update(coverage)
    c01, c04 = num("C01"), num("C04")
    derive("C10", round(c04 / c01, 6) if c04 is not None and c01 else None, ["C04", "C01"])
    return values


# ---------------------------------------------------------------- problem and cause rules
def _pct(value):
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt(value, unit=""):
    if value is None:
        return "—"
    text = f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else f"{value:,.0f}"
    return f"{text} {unit}".strip()


def _level_name(level):
    return {"1": "战略大客户", "2": "重要大客户", "3": "一般客户", "4": "BG 大客户"}.get(level, level)


def evaluate(data, config, measured):
    """Settle every problem and cause the data can settle; collect the evidence."""
    values = metric_values(data, config)
    results = data.get("results") or {}
    facts, records = {}, []

    def fact(code):
        entry = values.get(code) or {}
        fid = f"ss:metric:{code}"
        if fid not in facts:
            value, unit = entry.get("value"), entry.get("unit", "")
            if unit in {"%", "比值"} and value is not None:
                # Ratio metrics are 0–1 decimals; facts carry them as percentages.
                value, unit = round(value * 100, 4), "%"
            facts[fid] = dict(id=fid, label=entry.get("name", code), value=value, unit=unit,
                              definition=(config["metrics"].get(code) or {}).get("definition", ""),
                              source="customer PostgreSQL · ded_public", status=entry.get("status"))
        return fid

    def num(code):
        return (values.get(code) or {}).get("value")

    def observed(*codes):
        return [dict(id=f"ss:metric:{code}", label=f"{code} {(values.get(code) or {}).get('name', code)}",
                     value=num(code), unit=(values.get(code) or {}).get("unit", "")) for code in codes]

    issues = config["issues"]
    out = {}

    def settle(code, status, *, level="", description="", codes=(), missing=()):
        spec = issues[code]
        indicator_codes = [c for c in re.split(r"[、,，]", spec["indicators"]) if c]
        used = list(dict.fromkeys(list(codes) or indicator_codes))
        out[code] = dict(code=code, ruleStatus=status, level=level, description=description,
                         observed=observed(*used), evidenceIds=[fact(c) for c in used if c in values],
                         missingEvidence=list(missing))

    def missing_of(*codes):
        return [c for c in codes if num(c) is None]

    params = {code: spec.get("params") or {} for code, spec in issues.items()}

    # IS01 销售额与出货量双双落后时间进度
    r01, r02, b05 = num("R01"), num("R02"), num("B05")
    if None in (r01, r02, b05):
        settle("IS01", "insufficient", missing=missing_of("R01", "R02", "B05"))
    elif r01 < b05 and r02 < b05:
        lag = max(b05 - r01, b05 - r02) * 100
        p = params["IS01"]
        level = "极高" if lag >= p.get("lagExtremePoints", 15) else "高" if lag >= p.get("lagHighPoints", 10) else "中"
        settle("IS01", "triggered", level=level, description=(
            f"销售额达成率 {_pct(r01)}、出货量达成率 {_pct(r02)}，均低于时间进度 {_pct(b05)}，"
            f"最多落后 {lag:.1f} 个百分点。"))
    else:
        settle("IS01", "not_triggered")
    # IS02 全年预计达成缺口
    r05, r07 = num("R05"), num("R07")
    below = [(name, value) for name, value in (("销售额", r05), ("出货量", r07)) if value is not None and value < 1]
    if below:
        worst = min(value for _, value in below)
        settle("IS02", "triggered", level="高" if worst < params["IS02"].get("highBelow", 0.9) else "中",
               description="全年" + "、".join(f"{name}预计达成率 {_pct(value)}" for name, value in below) + "，低于 100%。")
    elif r05 is None or r07 is None:
        settle("IS02", "insufficient", missing=missing_of("R05", "R07"))
    else:
        settle("IS02", "not_triggered")
    # IS03 量价背离
    r03 = num("R03")
    if r03 is None:
        settle("IS03", "insufficient", missing=missing_of("R01", "R02"))
    elif abs(r03) >= params["IS03"].get("gapPoints", 10):
        faster = "销售额" if r03 > 0 else "出货量"
        settle("IS03", "triggered", level="高" if abs(r03) >= params["IS03"].get("highGapPoints", 20) else "中",
               description=f"销售额达成率 {_pct(r01)}、出货量达成率 {_pct(r02)}，相差 {abs(r03):.1f} 个百分点，{faster}进度更快。")
    else:
        settle("IS03", "not_triggered")
    # IS04 超期订未发积压
    s05, s06, s08 = num("S05"), num("S06"), num("S08")
    if s05 is None or s08 is None:
        settle("IS04", "insufficient", missing=missing_of("S05", "S08"))
    elif s05 > 0 and s08 >= params["IS04"].get("share", 0.2):
        settle("IS04", "triggered", level="高" if s08 >= params["IS04"].get("highShare", 0.5) else "中",
               description=f"超期订未发金额 {_fmt(s05, '亿元')}" + (f"、电量 {_fmt(s06, 'GWh')}" if s06 is not None else "")
               + f"，占订未发金额 {_pct(s08)}。")
    else:
        settle("IS04", "not_triggered")
    # IS05 在手订单不足以覆盖剩余目标
    c09 = values["C09"]
    gaps = [(name, cov, rem) for name, cov, rem in (("金额", c09.get("amount"), c09.get("remainingAmount")),
                                                     ("电量", c09.get("energy"), c09.get("remainingEnergy")))]
    short = [(name, cov) for name, cov, _ in gaps if cov is not None and cov < 1]
    if short:
        worst = min(cov for _, cov in short)
        settle("IS05", "triggered", level="高" if worst < params["IS05"].get("highBelow", 0.5) else "中",
               description="在手订未发对剩余目标的覆盖率：" + "、".join(f"{name} {_pct(cov)}" for name, cov in short)
               + f"（剩余目标金额 {_fmt(c09.get('remainingAmount'), '亿元')}、电量 {_fmt(c09.get('remainingEnergy'), 'GWh')}）。")
    elif all(rem is not None and rem <= 0 for _, _, rem in gaps):
        settle("IS05", "not_applicable")
    elif all(cov is None for _, cov, _ in gaps):
        settle("IS05", "insufficient", missing=missing_of("S03", "S04", "B01", "B02", "B03", "B04"))
    else:
        settle("IS05", "not_triggered")
    # IS06 订单履约率偏低
    o03 = num("O03")
    if o03 is None:
        settle("IS06", "insufficient", missing=["O03"])
    elif o03 < params["IS06"].get("below", 0.8):
        settle("IS06", "triggered", level="高" if o03 < params["IS06"].get("highBelow", 0.6) else "中",
               description=f"订单履约率 {_pct(o03)}，低于 {_pct(params['IS06'].get('below', 0.8))}。")
    else:
        settle("IS06", "not_triggered")
    # IS07 重点客户电量缺口
    c08 = values.get("C08") or {}
    if c08.get("status") != "ok":
        settle("IS07", "insufficient", missing=["C08"])
    else:
        hits = []
        for group in c08.get("groups") or []:
            level = group["dims"].get("D005", "")
            key = next((k for k, name in STRATEGIC_LEVELS.items() if level in (k, name)), None)
            if key and group["value"] is not None and group["value"] > 0:
                hits.append((key, group["value"]))
                records.append(dict(id=f"ss:customer-level:{key}", label=f"{_level_name(key)}电量缺口",
                                    value=group["value"], unit="MWh"))
        if hits:
            settle("IS07", "triggered", level="高" if any(key == "1" for key, _ in hits) else "中",
                   description="、".join(f"{_level_name(key)}电量缺口 {_fmt(value, 'MWh')}" for key, value in hits) + "。")
        else:
            settle("IS07", "not_triggered")
    # IS08 订单取消／变更冲减
    o04, o01 = num("O04"), num("O01")
    if o04 is None:
        settle("IS08", "insufficient", missing=["O04"])
    elif o04 > 0:
        share = o04 / o01 if o01 else None
        settle("IS08", "triggered",
               level="高" if share is not None and share >= params["IS08"].get("highShare", 0.05) else "中",
               description=f"取消／变更订单电量 {_fmt(o04, 'GWh')}" + (f"，占订单接收电量 {_pct(share)}" if share is not None else "") + "。")
    else:
        settle("IS08", "not_triggered")

    # DQ01 指标取数失败或超时
    failed = [(code, item) for code, item in results.items() if item.get("status") not in ("ok",)]
    if failed:
        core = set(str(params["DQ01"].get("core", "")).split(","))
        names = [f"{code} {config['metrics'][code]['name']}（{item.get('status')}"
                 + (f"·{(item.get('error') or {}).get('code')}" if (item.get('error') or {}).get('code') else "") + "）"
                 for code, item in failed]
        settle("DQ01", "triggered", level="高" if any(code in core for code, _ in failed) else "中",
               description=f"{len(failed)} 项指标取数未成功：" + "、".join(names[:8]) + ("等。" if len(names) > 8 else "。"),
               codes=[code for code, _ in failed])
    else:
        settle("DQ01", "not_triggered")
    # DQ02 核心指标结果为空
    empty = [code for code in CORE_METRICS if (results.get(code) or {}).get("status") == "ok" and num(code) is None]
    if empty:
        settle("DQ02", "triggered", level="高", description="取数成功但结果为空：" + "、".join(
            f"{code} {config['metrics'][code]['name']}" for code in empty) + "。", codes=empty)
    else:
        settle("DQ02", "not_triggered")
    # DQ03 达成率与基础指标不一致
    tolerance = params["DQ03"].get("tolerance", 0.01)
    pairs = [("R01", r01, num("B02"), num("B01"), "销售额达成率"), ("R02", r02, num("B04"), num("B03"), "出货量达成率")]
    checks = [(code, rate, part / whole, label) for code, rate, part, whole, label in pairs
              if rate is not None and part is not None and whole]
    off = [(code, rate, recomputed, label) for code, rate, recomputed, label in checks if abs(rate - recomputed) > tolerance]
    if off:
        settle("DQ03", "triggered", level="中", description="；".join(
            f"{label} {_pct(rate)}，按实绩 ÷ 目标复算为 {_pct(recomputed)}" for _, rate, recomputed, label in off) + "。")
    elif checks:
        settle("DQ03", "not_triggered")
    else:
        settle("DQ03", "insufficient", missing=missing_of("R01", "B01", "B02", "R02", "B03", "B04"))
    # DQ04 订未发结构不闭合
    s04, s07 = num("S04"), num("S07")
    if None in (s04, s05, s07):
        settle("DQ04", "insufficient", missing=missing_of("S04", "S05", "S07"))
    elif s04 <= 0:
        settle("DQ04", "not_applicable")
    elif abs(s05 + s07 - s04) / s04 > params["DQ04"].get("tolerance", 0.05):
        settle("DQ04", "triggered", level="中", description=(
            f"超期订未发 {_fmt(s05, '亿元')} ＋ 正常订未发 {_fmt(s07, '亿元')} ＝ {_fmt(s05 + s07, '亿元')}，"
            f"与未发货金额 {_fmt(s04, '亿元')} 相差 {_pct(abs(s05 + s07 - s04) / s04)}。"))
    else:
        settle("DQ04", "not_triggered")
    # DQ05 计划外发货无法核对
    s02, s09_status = num("S02"), (results.get("S09") or {}).get("status")
    if s02 is None:
        settle("DQ05", "insufficient", missing=["S02"])
    elif s02 <= 0:
        settle("DQ05", "not_applicable")
    elif s09_status == "ok" and num("S09") is None:
        settle("DQ05", "triggered", level="中", description=(
            f"已发货金额 {_fmt(s02, '亿元')}，但计划外发货金额为空（日出货计划缺失或行匹配不唯一）。"))
    else:
        settle("DQ05", "not_triggered")
    # DQ06 客户电量缺口单侧缺失
    c07 = values.get("C07") or {}
    if c07.get("status") != "ok" or c08.get("status") != "ok":
        settle("DQ06", "insufficient", missing=[c for c in ("C07", "C08") if (values.get(c) or {}).get("status") != "ok"])
    else:
        gap_by_level = {g["dims"].get("D005", ""): g["value"] for g in c08.get("groups") or []}
        one_sided = [g["dims"].get("D005", "") for g in c07.get("groups") or []
                     if g["value"] is not None and gap_by_level.get(g["dims"].get("D005", "")) is None]
        if one_sided:
            settle("DQ06", "triggered", level="中", description="客户等级 " + "、".join(
                _level_name(level) for level in one_sided) + " 有实际发货电量但电量缺口为空（目标缺失）。")
        else:
            settle("DQ06", "not_triggered")

    # ---- causes ---------------------------------------------------------
    causes = config["causes"]
    outcomes = {}

    def cause_outcome(code, status, *, reason, description="", codes=(), missing=()):
        spec = causes[code]
        used = list(dict.fromkeys(list(codes) or [c for c in re.split(r"[、,，]", spec["indicators"]) if c]))
        outcomes[code] = dict(code=code, ruleStatus=status, reason=reason, description=description or reason,
                              kind="verified" if status == "triggered" else "hypothesis",
                              observed=observed(*used), evidenceIds=[fact(c) for c in used if c in values],
                              missingEvidence=list(missing))

    c03 = num("C03")
    if c03 is None:
        cause_outcome("RC01", "insufficient", reason="商机预测缺口未取到", missing=["C03"])
    elif c03 > 0:
        cause_outcome("RC01", "triggered", reason=f"商机预测缺口 {_fmt(c03, '亿元')}，上游商机预测不足以覆盖目标。")
    else:
        cause_outcome("RC01", "not_triggered", reason=f"商机预测缺口 {_fmt(c03, '亿元')}，未见上游覆盖不足。")
    c10 = num("C10")
    if c10 is None or b05 is None:
        cause_outcome("RC02", "insufficient", reason="已签单商机占比或时间进度未取到", missing=missing_of("C04", "C01", "B05"))
    elif c10 < b05:
        cause_outcome("RC02", "triggered", reason=f"已签单商机占比 {_pct(c10)}，低于时间进度 {_pct(b05)}。")
    else:
        cause_outcome("RC02", "not_triggered", reason=f"已签单商机占比 {_pct(c10)}，不低于时间进度 {_pct(b05)}。")
    s12 = values.get("S12") or {}
    if s05 is None:
        cause_outcome("RC03", "insufficient", reason="超期订未发金额未取到", missing=["S05"])
    elif s05 > 0 and (s12.get("count") or 0) > 0:
        top = sorted((g for g in s12.get("groups") or [] if g["value"]), key=lambda g: -g["value"])[:10]
        for group in top:
            order_no = group["dims"].get("D049") or "未知订单"
            records.append(dict(id=f"ss:order:{order_no}", label=f"超期订单 {order_no}", value=group["value"], unit="天",
                                customer=group["dims"].get("D006", ""), due=group["dims"].get("D050", "")))
        cause_outcome("RC03", "triggered", reason=(
            f"超期订未发金额 {_fmt(s05, '亿元')}，{s12.get('count')} 张订单已超期，最长 {_fmt(s12.get('value'), '天')}。"))
    elif s05 > 0:
        cause_outcome("RC03", "insufficient", reason="有超期订未发金额，但逐单超期天数未取到", missing=["S12"])
    else:
        cause_outcome("RC03", "not_triggered", reason="没有超期订未发金额。")
    s10, s11 = num("S10"), num("S11")
    if s10 is None or s11 is None:
        cause_outcome("RC04", "insufficient", reason="发货平均周期或标杆未取到", missing=missing_of("S10", "S11"))
    elif s10 > s11:
        cause_outcome("RC04", "triggered", reason=f"发货平均周期 {_fmt(s10, '天')}，超过标杆 {_fmt(s11, '天')}。")
    else:
        cause_outcome("RC04", "not_triggered", reason=f"发货平均周期 {_fmt(s10, '天')}，未超过标杆 {_fmt(s11, '天')}。")
    s09 = num("S09")
    if s09 is None:
        cause_outcome("RC05", "insufficient", reason="计划外发货金额为空，无法判断计划扰动", missing=["S09"])
    elif s09 > 0:
        cause_outcome("RC05", "triggered", reason=f"计划外发货金额 {_fmt(s09, '亿元')}。")
    else:
        cause_outcome("RC05", "not_triggered", reason="没有计划外发货金额。")
    r09, r10 = num("R09"), num("R10")
    if r09 is None or not r10:
        cause_outcome("RC06", "insufficient", reason="实际或目标单位电量销售额无法计算", missing=missing_of("B01", "B02", "B03", "B04"))
    elif abs(r09 - r10) / r10 >= causes["RC06"].get("params", {}).get("deviation", 0.1):
        cause_outcome("RC06", "triggered", reason=(
            f"实际单位电量销售额 {r09:.3f} 元/Wh，目标隐含 {r10:.3f} 元/Wh，偏离 {_pct(abs(r09 - r10) / r10)}。"))
    else:
        cause_outcome("RC06", "not_triggered", reason=f"实际与目标单位电量销售额偏离 {_pct(abs(r09 - r10) / r10)}，在阈值内。")
    c06 = num("C06")
    level_gaps = [g for g in c08.get("groups") or [] if g["value"] and g["value"] > 0
                  and any(g["dims"].get("D005", "") in (k, n) for k, n in STRATEGIC_LEVELS.items())]
    if c06 is None and c08.get("status") != "ok":
        cause_outcome("RC07", "insufficient", reason="待突破战略客户数与客户电量缺口均未取到", missing=["C06", "C08"])
    elif (c06 or 0) > 0 or level_gaps:
        cause_outcome("RC07", "triggered", reason=(
            (f"待突破战略客户 {int(c06)} 家" if c06 else "") + ("；" if c06 and level_gaps else "")
            + ("、".join(f"{_level_name(g['dims'].get('D005', ''))}电量缺口 {_fmt(g['value'], 'MWh')}" for g in level_gaps))) + "。")
    else:
        cause_outcome("RC07", "not_triggered", reason="没有待突破战略客户，战略 / 重要大客户也没有电量缺口。")
    s13 = values.get("S13") or {}
    if s13.get("status") != "ok":
        cause_outcome("RC08", "insufficient", reason="发货办理状态未取到", missing=["S13"])
    else:
        overdue = [(g["dims"].get("D024", ""), g["value"]) for g in s13.get("groups") or []
                   if (g["dims"].get("D024", "") in OVERDUE_HANDLING or g["dims"].get("D024", "") in OVERDUE_HANDLING.values())
                   and g["value"] and g["value"] > 0]
        if overdue:
            cause_outcome("RC08", "triggered", reason="、".join(
                f"{OVERDUE_HANDLING.get(state, state)} {_fmt(value, 'GWh')}" for state, value in overdue) + "。")
        else:
            cause_outcome("RC08", "not_triggered", reason="没有逾期未完成或逾期完成的发货办理电量。")
    if o04 is None:
        cause_outcome("RC09", "insufficient", reason="取消／变更订单电量未取到", missing=["O04"])
    elif o04 > 0:
        cause_outcome("RC09", "triggered", reason=f"取消／变更订单电量 {_fmt(o04, 'GWh')}。")
    else:
        cause_outcome("RC09", "not_triggered", reason="没有取消或变更订单。")
    dq = {code: out[code]["ruleStatus"] == "triggered" for code in ("DQ01", "DQ02", "DQ03", "DQ04", "DQ05", "DQ06")}
    cause_outcome("RC10", "triggered" if dq["DQ01"] else "not_triggered",
                  reason=out["DQ01"]["description"] or "全部调用SQL取数成功。",
                  codes=[code for code, _ in failed] or CORE_METRICS)
    missing_parts = [out[code]["description"] for code in ("DQ02", "DQ05", "DQ06") if dq[code]]
    cause_outcome("RC11", "triggered" if missing_parts else "not_triggered",
                  reason="；".join(missing_parts) or "未发现结果为空或单侧缺失的源数据。")
    mismatch = [out[code]["description"] for code in ("DQ03", "DQ04") if dq[code]]
    cause_outcome("RC12", "triggered" if mismatch else "not_triggered",
                  reason="；".join(mismatch) or "达成率复算与订未发结构均一致。")

    triggered = [dict(code=code, name=issues[code]["name"], level=item["level"], description=item["description"])
                 for code, item in out.items() if item["ruleStatus"] == "triggered"]
    evidence = dict(facts=list(facts.values()), records=records,
                    evidence=[dict(id=fid) for fid in facts] + [dict(id=r["id"]) for r in records],
                    counts=dict(facts=len(facts), records=len(records), referenced=len(facts) + len(records),
                                distinct=len(facts) + len(records)),
                    periods=[data.get("period")], dataAsOf=data.get("measurementDate"))
    return dict(values=values, risks=triggered, riskCandidates=list(out.values()), causeOutcomes=outcomes,
                evidence=evidence, result=dict(measurementDate=data.get("measurementDate")),
                metrics={code: {k: v for k, v in entry.items() if k != "groups"} for code, entry in values.items()})


# ---------------------------------------------------------------- card
def _trace(config):
    def entries(section, extra=()):
        return [dict(code=code, name=v2._text(item.get("name")) or code,
                     **{key: v2._text(item.get(key)) for key in extra})
                for code, item in (config.get(section) or {}).items()]
    return dict(ontology=config.get("ontology"), version=config.get("version"), digest=config_digest()[:12],
                links=json.loads(json.dumps(config.get("links") or {})),
                metrics=entries("metrics", ("definition", "unit", "resultColumn", "sqlStatus")),
                risks=entries("issues", ("type", "condition")), causes=entries("causes", ("stage",)),
                advice=entries("advice"), rules=entries("rules", ("description", "trigger", "result")))


def build_card(period, database=None, measurement_date=None, config=None, judge=None, progress=None,
               diagnostic_reporter=None):
    """Build one complete ``combined`` (销售额／出货量共同问题分析) publication payload."""
    v2._report_progress(progress, "ontology", message="读取本体与规则配置")
    config = config or load_config()
    started = time.monotonic()
    measured = v2._measurement_context(str(period), measurement_date)
    data = collect(period, measured, database=database, config=config, progress=progress,
                   diagnostic_reporter=diagnostic_reporter)
    usable = [code for code, item in data["results"].items() if item.get("status") == "ok"]
    if not usable:
        error = SalesShipmentUnavailable("全部调用SQL取数失败，没有可用于分析的数据："
                                         + "；".join(f"{e['stage']} {e['code']}" for e in data["errors"][:6]))
        error.phase, error.code = "database_query", "ALL_QUERIES_FAILED"
        error.diagnostic_message = str(error)
        raise error
    v2._report_progress(progress, "rules", message="规则函数判定问题与根因")
    evaluated = evaluate(data, config, measured)
    v2._report_progress(progress, "analysing", message="逐条判定规则无法确定的问题与根因")
    view = dict(config, risks=config["issues"])
    judged = judge_card(
        evaluated, view, judge=judge, progress=progress, primary="issue", id_prefix="ss",
        cause_stage=lambda code: (config["causes"].get(code) or {}).get("stage") or "data",
        advice_type=lambda code, spec, linked: (
            "remediation" if any(c.get("kind") == "verified" and c.get("status") == "supported" for c in linked or [])
            else "investigation"))
    issue_types = {code: spec["type"] for code, spec in config["issues"].items()}
    for finding in judged["findings"]:
        finding["issueType"] = issue_types.get(finding["riskCode"], "")
    notes = config.get("notes") or {}
    limitations = [f"{e['stage']} 取数未成功（{e['code']}）：{e['message']}" for e in data["errors"]][:10]
    limitations += [note for note in (notes.get("caliber"), notes.get("dataGaps")) if note]
    if notes.get("pending"):
        limitations.append("部分问题阈值为建议值，待业务确认（见本体“说明·待确认”）。")
    failures = judged["ontologyJudgement"]["failures"]
    result = dict(judged)
    result.update(
        businessSummary=judged["summary"], limitations=limitations, queryCatalog=data["queryCatalog"],
        ontologyTrace=_trace(config), measurementDate=measured.isoformat(), primaryLabel="问题",
        issueTypes=issue_types, cardContract="cockpit-cards-v1", engine="sales-shipment-rules",
        dataDiagnostics=["模型判断失败已跳过：" + item for item in failures][:20],
        analysisAssembly=dict(cardWriter="rules", modelContract="item-judgement-v1",
                              modelCalls=judged["ontologyJudgement"]["modelCalls"], modelFailures=len(failures)),
    )
    link_queries(result, view)
    v2._report_progress(progress, "publishing", message="发布卡片")
    fingerprint = hashlib.sha256(json.dumps(dict(period=str(period), measured=measured.isoformat(),
                                                 metrics=evaluated["metrics"]), ensure_ascii=False,
                                            sort_keys=True, default=str).encode()).hexdigest()
    return dict(
        id=uuid.uuid4().hex,
        status="limited" if (data["errors"] or failures) else "completed",
        context=dict(stage=STAGE, slotId=SLOT_ID, period=str(period), id=1, dataFingerprint=fingerprint,
                     ontologyVersion=config.get("version"), source="sales-shipment-ontology",
                     measurementDate=measured.isoformat(), stageName="销售额／出货量共同问题"),
        result=result, evidence=evaluated["evidence"], metrics=evaluated["metrics"],
        execution=dict(engine="sales-shipment-rules", durationSeconds=round(time.monotonic() - started, 3),
                       queryDurationSeconds=data["durationSeconds"], fetchedAt=time.time(),
                       source="customer PostgreSQL", measurementDate=measured.isoformat(),
                       rulesVersion=config.get("version"), configDigest=config_digest(),
                       queryCount=len(data["queryCatalog"]), errorCount=len(data["errors"]),
                       queryTimeoutMs=data["queryTimeoutMs"], fetchBudgetSeconds=data["fetchBudgetSeconds"]),
    )


__all__ = ["SLOT_ID", "STAGE", "RULES_VERSION", "SalesShipmentUnavailable", "load_config", "config_digest",
           "collect", "metric_values", "evaluate", "build_card", "item_judge", "role_prompt", "summary_role"]
