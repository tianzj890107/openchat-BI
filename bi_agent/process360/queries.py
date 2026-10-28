"""Controlled S03 statements for SC01-SC05.

Every statement is fixed in this module, parameterised, and read-only.  Callers
select a scenario code; they cannot supply SQL.  Missing mappings are returned
as explicit blocked metrics and gaps, never as zero.
"""

from __future__ import annotations

from datetime import date
from dataclasses import replace
from contextlib import nullcontext
from typing import Any

from .catalog import Process360Catalog
from .db import DatabaseQueryError, QueryResult, schema_table
from .models import Scope, envelope, evidence, gap, metric


def _table(schema: str, name: str) -> str:
    return schema_table(schema, name)


def _filters(
    scope: Scope, *, customer_column: str = "", owner_column: str = "", product_column: str = ""
) -> tuple[str, dict[str, Any]]:
    parts: list[str] = []
    params: dict[str, Any] = {}
    if scope.customer_ids and customer_column:
        parts.append(f"AND {customer_column} = ANY(%(customer_ids)s)")
        params["customer_ids"] = list(scope.customer_ids)
    if scope.owner_ids and owner_column:
        parts.append(f"AND {owner_column} = ANY(%(owner_ids)s)")
        params["owner_ids"] = list(scope.owner_ids)
    if scope.product_ids and product_column:
        parts.append(f"AND {product_column} = ANY(%(product_ids)s)")
        params["product_ids"] = list(scope.product_ids)
    return " ".join(parts), params


def _metric_row(catalog: Process360Catalog, code: str) -> dict[str, Any]:
    return dict(catalog.metric(code) or {"code": code, "name": code})


def _metric_name(catalog: Process360Catalog, code: str) -> str:
    row = catalog.metric(code) or {}
    return str(row.get("name") or row.get("指标名称") or code)


def _metric_formula(catalog: Process360Catalog, code: str) -> str:
    row = catalog.metric(code) or {}
    return str(row.get("计算公式") or "")


def _query_catalog_gap(
    catalog: Process360Catalog, code: str, *, severity: str = "blocking"
) -> dict[str, Any]:
    row = catalog.get("gaps", code) or {}
    return gap(
        code,
        str(row.get("name") or row.get("事项") or code),
        needed=str(row.get("必须补充") or ""),
        impact=str(row.get("影响范围") or ""),
        severity=severity,
    )


def _blocked_metric(
    catalog: Process360Catalog, code: str, *, reason: str, gap_code: str = ""
) -> dict[str, Any]:
    return metric(
        code,
        _metric_name(catalog, code),
        None,
        str((catalog.metric(code) or {}).get("单位") or ""),
        status="blocked",
        formula=_metric_formula(catalog, code),
        note=reason,
        evidence=gap_code,
    )


def _empty(columns: list[str]) -> QueryResult:
    return QueryResult(columns, [], 0, False)


# ---------------------------------------------------------------------------
# SC01 — overdue order balance
# ---------------------------------------------------------------------------

SC01_AGGREGATE = """
WITH plan_versioned AS (
  SELECT d."AT0001303" AS plan_id,
         d."AT0001305" AS plan_date,
         d."AT0001313" AS planned_qty,
         d."AT0001316" AS has_daily_plan,
         d."AT0001317" AS remaining_qty,
         d."AT0001320" AS month_id,
         d."AT0001321" AS order_id,
         d."AT0001323" AS product_id,
         d."AT0001325" AS line_no,
         d."AT0001333" AS modified_on,
         d."AT0001335" AS version_no,
         m."AT0001357" AS align_status,
         m."AT0001358" AS line_id,
         ROW_NUMBER() OVER (
           PARTITION BY d."AT0001321", d."AT0001325", d."AT0001323", d."AT0001305", d."AT0001320"
           ORDER BY d."AT0001333" DESC NULLS LAST, d."AT0001335" DESC NULLS LAST, d."AT0001303" DESC
         ) AS rn
  FROM {plan} d
  JOIN {month} m ON m."AT0001377" = d."AT0001320" AND m."AT0001361" = 0
  WHERE d."AT0001329" = 0
),
base AS (
  SELECT p.plan_id, p.plan_date, p.remaining_qty, p.product_id, p.order_id, p.line_no,
         l."AT0001155" AS unit_price,
         CASE WHEN TRIM(l."AT0001128") ~ '^[0-9]+([.][0-9]+)?$' THEN NULLIF(TRIM(l."AT0001128")::numeric, 0) ELSE NULL END AS price_unit,
         pr."AT9200243" AS kwh_per_unit,
         l."AT0001235" AS delivery_date,
         l."AT0001253" AS owner_id,
         o."AT0001089" AS customer_id,
         a."AT9200661" AS customer_name
  FROM plan_versioned p
  JOIN {line} l ON l."AT0001122" = p.line_id
               AND l."AT0001230" = p.order_id
               AND l."AT0001237" = p.line_no
  JOIN {order} o ON o."AT0000927" = p.order_id AND o."AT0001090" = 0
  LEFT JOIN {product} pr ON pr."AT9200241" = p.product_id
  LEFT JOIN {account} a ON a."AT9200384" = o."AT0001089"
  WHERE p.rn = 1 AND p.remaining_qty > 0
),
eligible AS (
  SELECT * FROM base
  WHERE delivery_date IS NOT NULL AND DATE(delivery_date) < %(cutoff)s
  {filters}
)
SELECT COUNT(*) AS overdue_rows,
       CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(remaining_qty * unit_price * price_unit) END / 100000000.0 AS amount_100m,
       CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(remaining_qty * CASE WHEN kwh_per_unit > 0 THEN kwh_per_unit ELSE NULL END) END / 1000000.0 AS power_gwh,
       COUNT(*) FILTER (WHERE kwh_per_unit IS NULL OR kwh_per_unit <= 0) AS zero_power_rows,
       COUNT(*) FILTER (WHERE unit_price IS NULL OR price_unit IS NULL) AS missing_price_rows,
       MIN(plan_date) AS first_plan_date,
       MAX(plan_date) AS last_plan_date
FROM eligible
"""

SC01_ROWS = """
WITH plan_versioned AS (
  SELECT d."AT0001303" AS plan_id, d."AT0001305" AS plan_date, d."AT0001317" AS remaining_qty,
         d."AT0001320" AS month_id, d."AT0001321" AS order_id, d."AT0001323" AS product_id,
         d."AT0001325" AS line_no, d."AT0001333" AS modified_on, d."AT0001335" AS version_no,
         m."AT0001357" AS align_status, m."AT0001358" AS line_id,
         ROW_NUMBER() OVER (
           PARTITION BY d."AT0001321", d."AT0001325", d."AT0001323", d."AT0001305", d."AT0001320"
           ORDER BY d."AT0001333" DESC NULLS LAST, d."AT0001335" DESC NULLS LAST, d."AT0001303" DESC
         ) AS rn
  FROM {plan} d
  JOIN {month} m ON m."AT0001377" = d."AT0001320" AND m."AT0001361" = 0
  WHERE d."AT0001329" = 0
)
SELECT p.order_id, p.line_no, p.product_id, p.plan_id, p.plan_date, p.remaining_qty,
       l."AT0001235" AS delivery_date, l."AT0001253" AS owner_id,
       o."AT0001089" AS customer_id, a."AT9200661" AS customer_name,
       l."AT0001155" AS unit_price, CASE WHEN TRIM(l."AT0001128") ~ '^[0-9]+([.][0-9]+)?$' THEN NULLIF(TRIM(l."AT0001128")::numeric, 0) ELSE NULL END AS price_unit,
       pr."AT9200243" AS kwh_per_unit,
       p.remaining_qty * l."AT0001155" * CASE WHEN TRIM(l."AT0001128") ~ '^[0-9]+([.][0-9]+)?$' THEN NULLIF(TRIM(l."AT0001128")::numeric, 0) ELSE NULL END / 100000000.0 AS amount_100m,
       p.remaining_qty * pr."AT9200243" / 1000000.0 AS power_gwh,
       p.align_status, p.modified_on
FROM plan_versioned p
JOIN {line} l ON l."AT0001122" = p.line_id AND l."AT0001230" = p.order_id AND l."AT0001237" = p.line_no
JOIN {order} o ON o."AT0000927" = p.order_id AND o."AT0001090" = 0
LEFT JOIN {product} pr ON pr."AT9200241" = p.product_id
LEFT JOIN {account} a ON a."AT9200384" = o."AT0001089"
WHERE p.rn = 1 AND p.remaining_qty > 0
  AND l."AT0001235" IS NOT NULL AND DATE(l."AT0001235") < %(cutoff)s
  {filters}
ORDER BY (p.remaining_qty * l."AT0001155" * CASE WHEN TRIM(l."AT0001128") ~ '^[0-9]+([.][0-9]+)?$' THEN NULLIF(TRIM(l."AT0001128")::numeric, 0) ELSE NULL END) DESC NULLS LAST
LIMIT %(limit)s
"""

SC01_MISSING = """
WITH plan_versioned AS (
  SELECT d."AT0001303" AS plan_id, d."AT0001321" AS order_id, d."AT0001325" AS line_no,
         d."AT0001323" AS product_id, d."AT0001305" AS plan_date,
         d."AT0001317" AS remaining_qty, m."AT0001358" AS line_id,
         ROW_NUMBER() OVER (
           PARTITION BY d."AT0001321", d."AT0001325", d."AT0001323", d."AT0001305", d."AT0001320"
           ORDER BY d."AT0001333" DESC NULLS LAST, d."AT0001335" DESC NULLS LAST, d."AT0001303" DESC
         ) AS rn
  FROM {plan} d
  JOIN {month} m ON m."AT0001377" = d."AT0001320" AND m."AT0001361" = 0
  WHERE d."AT0001329" = 0
)
SELECT COUNT(*) FILTER (WHERE l."AT0001235" IS NULL) AS missing_delivery_date,
       COUNT(*) FILTER (WHERE pr."AT9200243" IS NULL OR pr."AT9200243" <= 0) AS zero_power_rows,
       COUNT(*) FILTER (WHERE l."AT0001155" IS NULL OR (CASE WHEN TRIM(l."AT0001128") ~ '^[0-9]+([.][0-9]+)?$' THEN NULLIF(TRIM(l."AT0001128")::numeric, 0) ELSE NULL END) IS NULL) AS missing_price_rows
FROM plan_versioned p
JOIN {line} l ON l."AT0001122" = p.line_id AND l."AT0001230" = p.order_id AND l."AT0001237" = p.line_no
JOIN {order} o ON o."AT0000927" = p.order_id AND o."AT0001090" = 0
LEFT JOIN {product} pr ON pr."AT9200241" = p.product_id
WHERE p.rn = 1 AND p.remaining_qty > 0
{filters}
"""


def query_sc01(catalog: Process360Catalog, scope: Scope, db: Any) -> dict[str, Any]:
    schema = getattr(getattr(db, "config", None), "schema", "ywln_crm")
    today = date.today()
    cutoff = scope.observation_cutoff(today)
    if cutoff < today and not scope.include_current_snapshot:
        return envelope(
            "S03",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario="SC01",
            scope=scope,
            metrics=[
                _blocked_metric(
                    catalog,
                    code,
                    reason="所选截止日早于当前日期，源视图没有可验证的历史计划快照；不以当前余额回填历史。",
                    gap_code="G16",
                )
                for code in ("M0143", "M0134", "M0336", "M0337")
            ],
            gaps=[_query_catalog_gap(catalog, "G16")],
            limitations=["历史时点的有效计划版本和订单行版本无法从当前视图还原。"],
            next_steps=["将截止日改为当前日期，或提供计划历史快照后再取数。"],
        )
    agg_filters, params = _filters(
        scope,
        customer_column="customer_id",
        owner_column="owner_id",
        product_column="product_id",
    )
    row_filters, _same = _filters(
        scope,
        customer_column='o."AT0001089"',
        owner_column='l."AT0001253"',
        product_column="p.product_id",
    )
    params.update({"cutoff": cutoff, "limit": scope.limit})
    aggregate = db.run(
        SC01_AGGREGATE.format(
            plan=_table(schema, "LE000013"),
            month=_table(schema, "LE000014"),
            line=_table(schema, "LE000011"),
            order=_table(schema, "LE000010"),
            product=_table(schema, "LE000029"),
            account=_table(schema, "LE000027"),
            filters=agg_filters,
        ),
        params,
    )
    detail = db.run(
        SC01_ROWS.format(
            plan=_table(schema, "LE000013"),
            month=_table(schema, "LE000014"),
            line=_table(schema, "LE000011"),
            order=_table(schema, "LE000010"),
            product=_table(schema, "LE000029"),
            account=_table(schema, "LE000027"),
            filters=row_filters,
        ),
        params,
    )
    missing = db.run(
        SC01_MISSING.format(
            plan=_table(schema, "LE000013"),
            month=_table(schema, "LE000014"),
            line=_table(schema, "LE000011"),
            order=_table(schema, "LE000010"),
            product=_table(schema, "LE000029"),
            filters=row_filters,
        ),
        params,
    )
    row = (aggregate.rows or [{}])[0]
    miss = (missing.rows or [{}])[0]
    amount = _number(row.get("amount_100m"))
    power = _number(row.get("power_gwh"))
    gaps: list[dict[str, Any]] = []
    status = "partial"  # G01: order-line active/version fields still require mapping acceptance.
    if int(miss.get("missing_delivery_date") or 0) > 0:
        gaps.append(
            gap(
                "DELIVERY_DATE_MISSING",
                "部分订单行缺少要求交期",
                needed="补齐 LE000011.requestdeliveryby",
                impact="这些行无法判定正常/超期，未计入超期汇总",
                severity="blocking",
                source="runtime",
            )
        )
        status = "partial"
    if int(miss.get("zero_power_rows") or 0) > 0:
        gaps.append(_query_catalog_gap(catalog, "G13", severity="degrading"))
        status = "partial"
    if int(miss.get("missing_price_rows") or 0) > 0:
        gaps.append(
            gap(
                "PRICE_MISSING",
                "部分订单行缺少有效单价/价格单位",
                needed="补齐 LE000011 未税单价与价格单位",
                impact="这些行未计入超期金额，金额被低估",
                severity="blocking",
                source="runtime",
            )
        )
        status = "partial"
    gaps.extend(
        [
            _query_catalog_gap(catalog, "G01", severity="degrading"),
            _query_catalog_gap(catalog, "G12", severity="degrading"),
            _query_catalog_gap(catalog, "G16", severity="degrading"),
        ]
    )
    metrics = [
        metric(
            "M0143",
            _metric_name(catalog, "M0143"),
            _rounded(amount),
            "亿元",
            formula=_metric_formula(catalog, "M0143"),
            evidence="EV01",
            status="partial",
            caliber=f"当前快照；观察截止日 {cutoff.isoformat()}；要求交期早于截止日",
        ),
        metric(
            "M0134",
            _metric_name(catalog, "M0134"),
            _rounded(power),
            "GWh",
            formula=_metric_formula(catalog, "M0134"),
            evidence="EV01",
            status="partial",
            note="零电量产品未计入电量；见 G13",
        ),
        metric(
            "M0336",
            _metric_name(catalog, "M0336"),
            _rounded(power),
            "GWh",
            formula=_metric_formula(catalog, "M0336"),
            evidence="EV01",
            status="partial",
        ),
        metric(
            "M0337",
            _metric_name(catalog, "M0337"),
            _rounded(amount),
            "亿元",
            formula=_metric_formula(catalog, "M0337"),
            evidence="EV01",
            status="partial",
        ),
    ]
    return envelope(
        "S03",
        status,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario="SC01",
        scope=scope,
        metrics=metrics,
        records=detail.rows,
        evidence_items=[
            evidence(
                "EV01",
                "订单与超期基准证据",
                source="ywln_crm LE000011/13/14/10/29/27",
                observed_at=cutoff.isoformat(),
                records=[
                    {
                        "overdueRows": row.get("overdue_rows"),
                        "amount100m": amount,
                        "powerGwh": power,
                    }
                ],
                limitations=["当前余额不能回填历史时点", "零电量/缺价行不静默补 0"],
            )
        ],
        gaps=gaps,
        limitations=[
            "日/月计划与订单头已按有效状态筛选；订单行 statecode/版本字段在当前映射缺失，G01 未验收，数值为暂定结果。",
            "计划按订单+行+产品+计划日期+月度计划键去重，取当前最新版本。",
        ],
        next_steps=["S04 识别异常与候选原因，缺证据的证据模板见 EV02"],
        queryInfo={
            "aggregateMs": aggregate.duration_ms,
            "detailMs": detail.duration_ms,
            "detailRows": len(detail.rows),
            "totalRows": max(
                int(row.get("overdue_rows") or 0), len(detail.rows)
            ),
            "truncated": detail.truncated
            or int(row.get("overdue_rows") or row.get("actual_rows") or 0) > len(detail.rows),
        },
        overdueRows=int(row.get("overdue_rows") or 0),
    )


# ---------------------------------------------------------------------------
# SC02 — quote approval and red-zone gap
# ---------------------------------------------------------------------------

SC02_AGGREGATE = """
WITH latest AS (
  SELECT q.*,
         ROW_NUMBER() OVER (PARTITION BY q."AT0000805" ORDER BY q."AT0000827" DESC NULLS LAST) AS rn
  FROM {quote} q
  WHERE q."AT0000823" = 0
)
SELECT COUNT(*) FILTER (WHERE TRIM("AT0000811") = '3' AND DATE("AT0000807") BETWEEN %(start)s AND %(end)s) AS approved_count,
       COUNT(*) FILTER (WHERE TRIM("AT0000811") IN ('1', '2') AND DATE("AT0000809") BETWEEN %(start)s AND %(end)s) AS in_progress_count,
       COUNT(*) FILTER (WHERE TRIM("AT0000811") = '4' AND DATE("AT0000807") BETWEEN %(start)s AND %(end)s) AS rejected_count,
       COUNT(*) FILTER (WHERE TRIM("AT0000811") = '3' AND "AT0000807" IS NULL) AS approved_without_time,
       COUNT(*) FILTER (WHERE TRIM("AT0000811") IN ('1', '2') AND "AT0000809" IS NULL) AS submitted_without_time
FROM latest WHERE rn = 1 {filters}
"""

SC02_ROWS = """
WITH latest AS (
  SELECT q.*,
         ROW_NUMBER() OVER (PARTITION BY q."AT0000805" ORDER BY q."AT0000827" DESC NULLS LAST) AS rn
  FROM {quote} q
  WHERE q."AT0000823" = 0
)
SELECT "AT0000805" AS quote_id, "AT0000813" AS quote_code, "AT0000811" AS status,
       "AT0000807" AS approved_at, "AT0000809" AS submitted_at,
       "AT0000820" AS customer_id, "AT0000821" AS owner_id
FROM latest
WHERE rn = 1 AND TRIM("AT0000811") = '3' AND DATE("AT0000807") BETWEEN %(start)s AND %(end)s
{filters}
ORDER BY "AT0000807" DESC NULLS LAST
LIMIT %(limit)s
"""


def query_sc02(catalog: Process360Catalog, scope: Scope, db: Any) -> dict[str, Any]:
    schema = getattr(getattr(db, "config", None), "schema", "ywln_crm")
    filters, params = _filters(scope, customer_column='"AT0000820"', owner_column='"AT0000821"')
    params.update(start=scope.period_start, end=scope.period_end, limit=scope.limit)
    aggregate = db.run(
        SC02_AGGREGATE.format(quote=_table(schema, "LE000007"), filters=filters), params
    )
    detail = db.run(SC02_ROWS.format(quote=_table(schema, "LE000007"), filters=filters), params)
    row = (aggregate.rows or [{}])[0]
    approved = int(row.get("approved_count") or 0)
    gaps = [
        _query_catalog_gap(catalog, "G02"),
        _query_catalog_gap(catalog, "G06", severity="degrading"),
        _query_catalog_gap(catalog, "G07", severity="degrading"),
    ]
    if int(row.get("approved_without_time") or 0) or int(row.get("submitted_without_time") or 0):
        gaps.append(
            gap(
                "QUOTE_TIME_MISSING",
                "部分报价缺审批/提交时间",
                needed="补齐 OA 审批时间与提交时间",
                impact="这些记录无法按期间归期，计数可能低估",
                severity="blocking",
                source="runtime",
            )
        )
    return envelope(
        "S03",
        "partial",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario="SC02",
        scope=scope,
        metrics=[
            metric(
                "M36001",
                _metric_name(catalog, "M36001"),
                approved,
                "单",
                formula=_metric_formula(catalog, "M36001"),
                evidence="EV04",
                status="partial" if row.get("approved_without_time") else "ok",
                caliber="报价申请单状态=3（审核通过），按批准日期归期",
            ),
            _blocked_metric(
                catalog,
                "M0137",
                reason="报价申请头没有可执行的红区价格区间映射；G02 未关闭，不能按 0 或全部报价代替。",
                gap_code="G02",
            ),
            _blocked_metric(
                catalog, "M36002", reason="分子 M0137 不可计算，不能输出占比。", gap_code="G02"
            ),
        ],
        records=detail.rows,
        evidence_items=[
            evidence(
                "EV04",
                "报价申请批准台账",
                source="ywln_crm LE000007",
                observed_at=scope.period_end.isoformat(),
                records=detail.rows,
                limitations=[
                    "只有申请头，红区价格区间/明细未映射；按当前记录状态与批准日期归期，不还原历史状态"
                ],
            )
        ],
        gaps=gaps,
        limitations=[
            "状态=3 才计为审核通过；状态 1/2 为进行中。",
            "红区报价单数和占比因缺价格区间映射而 blocked，不补 0。",
        ],
        next_steps=["补充报价明细价格区间/红区分界后计算 M0137/M36002"],
        queryInfo={
            "aggregateMs": aggregate.duration_ms,
            "detailMs": detail.duration_ms,
            "detailRows": len(detail.rows),
            "totalRows": max(int(approved or 0), len(detail.rows)),
            "truncated": detail.truncated or approved > len(detail.rows),
        },
        approvedCount=approved,
        counts={
            "inProgress": int(row.get("in_progress_count") or 0),
            "rejected": int(row.get("rejected_count") or 0),
            "approvedWithoutTime": int(row.get("approved_without_time") or 0),
        },
    )


# ---------------------------------------------------------------------------
# SC03 — strategic customer coverage
# ---------------------------------------------------------------------------

SC03_AGGREGATE = """
SELECT COUNT(*) AS strategic_customers,
       COUNT(*) FILTER (WHERE NOT EXISTS (
         SELECT 1 FROM {opportunity} o
         WHERE o."AT0000733" = a."AT9200384" AND o."AT0000745" = 1
       )) AS pending_customers
FROM {account} a
WHERE a."AT9200628" = 1 {filters}
"""

SC03_ROWS = """
SELECT a."AT9200384" AS customer_id, a."AT9200661" AS customer_name,
       a."AT9200628" AS account_level, a."AT9200679" AS created_at,
       EXISTS (
         SELECT 1 FROM {opportunity} o
         WHERE o."AT0000733" = a."AT9200384" AND o."AT0000745" = 1
       ) AS has_valid_opportunity,
       (SELECT COUNT(*) FROM {opportunity} o2
        WHERE o2."AT0000733" = a."AT9200384" AND o2."AT0000745" = 1) AS valid_opportunity_count
FROM {account} a
WHERE a."AT9200628" = 1
  {filters}
ORDER BY has_valid_opportunity ASC, valid_opportunity_count ASC, a."AT9200679" ASC
LIMIT %(limit)s
"""


def query_sc03(catalog: Process360Catalog, scope: Scope, db: Any) -> dict[str, Any]:
    schema = getattr(getattr(db, "config", None), "schema", "ywln_crm")
    filters, params = _filters(scope, customer_column='a."AT9200384"')
    params["limit"] = scope.limit
    rows = db.run(
        SC03_ROWS.format(
            account=_table(schema, "LE000027"),
            opportunity=_table(schema, "LE000006"),
            filters=filters,
        ),
        params,
    )
    aggregate = db.run(
        SC03_AGGREGATE.format(
            account=_table(schema, "LE000027"),
            opportunity=_table(schema, "LE000006"),
            filters=filters,
        ),
        params,
    )
    counts = (aggregate.rows or [{}])[0]
    if "strategic_customers" not in counts or "pending_customers" not in counts:
        raise DatabaseQueryError("战略客户汇总结果缺少全量计数字段")
    total = int(counts["strategic_customers"])
    pending = int(counts["pending_customers"])
    truncated = rows.truncated or total > len(rows.rows)
    return envelope(
        "S03",
        "partial",
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario="SC03",
        scope=scope,
        metrics=[
            metric(
                "M0257",
                _metric_name(catalog, "M0257"),
                pending,
                "户",
                formula=_metric_formula(catalog, "M0257"),
                evidence="EV06",
                status="ok",
                note="全量聚合计数，不受明细返回上限影响；客户等级=1 且无有效商机（statecode=1）。",
            ),
            _blocked_metric(
                catalog,
                "M36003",
                reason="缺少批准的年度/期间战略客户计划全集（G03），不能用当前客户表替代分母。",
                gap_code="G03",
            ),
            _blocked_metric(
                catalog,
                "M0140",
                reason="销售目标与商机预测的完整映射未验收，不能计算缺口。",
                gap_code="G03",
            ),
            _blocked_metric(
                catalog, "M0180", reason="未签单商机获取金额的完整映射未验收。", gap_code="G03"
            ),
        ],
        records=rows.rows,
        evidence_items=[
            evidence(
                "EV06",
                "战略客户与有效商机清单",
                source="ywln_crm LE000027/LE000006",
                observed_at=scope.period_end.isoformat(),
                records=rows.rows,
                limitations=["客户等级值 1 仅按已观察编码解释，需业务确认"],
            )
        ],
        gaps=[
            _query_catalog_gap(catalog, "G03"),
            _query_catalog_gap(catalog, "G06", severity="degrading"),
            _query_catalog_gap(catalog, "G07", severity="degrading"),
        ],
        limitations=[
            "M0257 是当前客户覆盖缺口，不是计划覆盖率；计划全集缺失时 M36003 blocked。",
            "客户等级编码 1 的含义需业务最终确认。",
        ],
        next_steps=["补充批准计划客户全集后计算 M36003", "对无有效商机的战略客户逐户核查"],
        queryInfo={
            "durationMs": rows.duration_ms,
            "detailRows": len(rows.rows),
            "totalRows": max(total, len(rows.rows)),
            "truncated": truncated,
        },
        strategicCustomers=total,
        pendingCustomers=pending,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# SC04 — awarded but unsigned
# ---------------------------------------------------------------------------

SC04_AGGREGATE = """
WITH latest AS (
  SELECT b.*,
         ROW_NUMBER() OVER (
           PARTITION BY b."AT9200002"
           ORDER BY b."AT9200003" DESC NULLS LAST, b."AT9200042" DESC NULLS LAST
         ) AS rn
  FROM {bid} b
  WHERE b."AT9200002" IS NOT NULL AND TRIM(b."AT9200002") <> ''
    AND b."AT9200042" IS NOT NULL
    AND b."AT9200003" IS NOT NULL AND b."AT9200003"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
)
SELECT COUNT(*) AS awarded_unsigned_rows,
       CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(b."AT9200102") END / 100000000.0 AS amount_100m,
       CASE WHEN COUNT(*) = 0 THEN 0 ELSE SUM(CASE WHEN b."AT9200013" > 0 THEN b."AT9200013" ELSE NULL END) END / 1000.0 AS power_gwh,
       AVG(%(cutoff)s::date - b."AT9200039"::date) AS avg_wait_days,
       MAX(%(cutoff)s::date - b."AT9200039"::date) AS max_wait_days,
       COUNT(*) FILTER (WHERE b."AT9200102" IS NULL) AS missing_amount,
       COUNT(*) FILTER (WHERE b."AT9200013" IS NULL OR b."AT9200013" <= 0) AS missing_energy
FROM latest b
JOIN {opportunity} o ON o."AT0000258" = b."AT9200041" AND o."AT0000434" = '3'
WHERE b.rn = 1
  AND b."AT9200036" IN ('是', '1')
  AND COALESCE(b."AT9200040", '') NOT LIKE '%%弃标%%'
  AND b."AT9200039" IS NOT NULL AND b."AT9200039"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
  AND NOT EXISTS (
    SELECT 1 FROM {order} so
    WHERE so."AT0001088" = o."AT0000258"
      AND so."AT0000999" = '1' AND so."AT0001014" = '1'
      AND COALESCE(so."AT0000953", 0) = 0 AND so."AT0001090" <> 2
      AND so."AT0001035" IN ('1', '3') AND so."AT0001064" = '5'
      AND so."AT0001112"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
  )
  {filters}
"""

SC04_ROWS = """
WITH latest AS (
  SELECT b.*,
         ROW_NUMBER() OVER (
           PARTITION BY b."AT9200002"
           ORDER BY b."AT9200003" DESC NULLS LAST, b."AT9200042" DESC NULLS LAST
         ) AS rn
  FROM {bid} b
  WHERE b."AT9200002" IS NOT NULL AND TRIM(b."AT9200002") <> ''
    AND b."AT9200042" IS NOT NULL
    AND b."AT9200003" IS NOT NULL AND b."AT9200003"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
)
SELECT b."AT9200042" AS bid_id, b."AT9200002" AS project_name, b."AT9200041" AS opportunity_id,
       b."AT9200013" AS energy_mwh, b."AT9200102" AS amount_rmb,
       b."AT9200039" AS awarded_at, b."AT9200011" AS region, b."AT9200016" AS cell_model,
       b."AT9200029" AS sales_person,
       (%(cutoff)s::date - b."AT9200039"::date) AS wait_days
FROM latest b
JOIN {opportunity} o ON o."AT0000258" = b."AT9200041" AND o."AT0000434" = '3'
WHERE b.rn = 1
  AND b."AT9200036" IN ('是', '1')
  AND COALESCE(b."AT9200040", '') NOT LIKE '%%弃标%%'
  AND b."AT9200039" IS NOT NULL AND b."AT9200039"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
  AND NOT EXISTS (
    SELECT 1 FROM {order} so
    WHERE so."AT0001088" = o."AT0000258"
      AND so."AT0000999" = '1' AND so."AT0001014" = '1'
      AND COALESCE(so."AT0000953", 0) = 0 AND so."AT0001090" <> 2
      AND so."AT0001035" IN ('1', '3') AND so."AT0001064" = '5'
      AND so."AT0001112"::timestamp < (%(cutoff)s::date + INTERVAL '1 day')
  )
  {filters}
ORDER BY b."AT9200102" DESC NULLS LAST
LIMIT %(limit)s
"""


def query_sc04(catalog: Process360Catalog, scope: Scope, db: Any) -> dict[str, Any]:
    schema = getattr(getattr(db, "config", None), "schema", "ywln_crm")
    filters, params = _filters(scope, customer_column='o."AT0000733"')
    params.update({"cutoff": scope.observation_cutoff(), "limit": scope.limit})
    aggregate = db.run(
        SC04_AGGREGATE.format(
            bid=_table(schema, "LE000022"),
            opportunity=_table(schema, "LE000006"),
            order=_table(schema, "LE000010"),
            filters=filters,
        ),
        params,
    )
    detail = db.run(
        SC04_ROWS.format(
            bid=_table(schema, "LE000022"),
            opportunity=_table(schema, "LE000006"),
            order=_table(schema, "LE000010"),
            filters=filters,
        ),
        params,
    )
    row = (aggregate.rows or [{}])[0]
    count = int(row.get("awarded_unsigned_rows") or 0)
    status = "partial"  # G04 relationship/cycle acceptance remains outstanding.
    gaps = [
        _query_catalog_gap(catalog, "G04", severity="degrading"),
        _query_catalog_gap(catalog, "G06", severity="degrading"),
        _query_catalog_gap(catalog, "G07", severity="degrading"),
    ]
    for field, code, title in (
        ("missing_amount", "BID_AMOUNT_MISSING", "部分中标记录缺少投标金额"),
        ("missing_energy", "BID_ENERGY_MISSING", "部分中标记录缺少有效电量"),
    ):
        if int(row.get(field) or 0) > 0:
            gaps.append(
                gap(
                    code,
                    title,
                    needed="补齐投标金额/电量",
                    impact="对应指标被低估",
                    severity="blocking",
                    source="runtime",
                )
            )
    return envelope(
        "S03",
        status,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario="SC04",
        scope=scope,
        metrics=[
            metric(
                "M0179",
                _metric_name(catalog, "M0179"),
                _number(row.get("amount_100m")),
                "亿元",
                formula=_metric_formula(catalog, "M0179"),
                evidence="EV08",
                status="partial" if row.get("missing_amount") else "ok",
            ),
            metric(
                "M0142",
                _metric_name(catalog, "M0142"),
                _number(row.get("power_gwh")),
                "GWh",
                formula=_metric_formula(catalog, "M0142"),
                evidence="EV08",
                status="partial" if row.get("missing_energy") else "ok",
            ),
            metric(
                "M36004",
                _metric_name(catalog, "M36004"),
                _number(row.get("avg_wait_days")),
                "天",
                formula=_metric_formula(catalog, "M36004"),
                evidence="EV08",
                caliber=f"评估日 {scope.observation_cutoff().isoformat()} 减中标结果公布日期；最大值 {row.get('max_wait_days')} 天",
            ),
        ],
        records=detail.rows,
        evidence_items=[
            evidence(
                "EV08",
                "中标未签台账",
                source="ywln_crm LE000022/LE000006/LE000010",
                observed_at=scope.observation_cutoff().isoformat(),
                records=detail.rows,
                limitations=["投标主键与商机关联来自 V3.1 映射，仍需 G04 业务验收"],
            )
        ],
        gaps=gaps,
        limitations=[
            "按项目名称取最新投标版本；弃标、未到公布时间、已有有效正式订单的记录排除。",
            "投标行与订单的关联依赖商机 ID；未关联商机的记录不进入指标。",
        ],
        next_steps=["逐项核查未签条款与等待天数", "补 G04 业务验收后再宣称可完整闭环"],
        queryInfo={
            "aggregateMs": aggregate.duration_ms,
            "detailMs": detail.duration_ms,
            "detailRows": len(detail.rows),
            "totalRows": max(int(count or 0), len(detail.rows)),
            "truncated": detail.truncated or count > len(detail.rows),
        },
        awardedUnsigned=count,
    )


# ---------------------------------------------------------------------------
# SC05 — planned vs actual shipment
# ---------------------------------------------------------------------------

SC05_BASE = """
WITH plan AS (
  SELECT d."AT0001321" AS order_id, d."AT0001325"::text AS line_no,
         d."AT0001323" AS product_id, d."AT0001305"::date AS plan_date,
         COUNT(*) AS plan_rows, MAX(TRIM(d."AT0001316")) AS has_daily_plan,
         SUM(d."AT0001313") AS planned_qty, MAX(m."AT0001357") AS align_status,
         COUNT(*) FILTER (WHERE l."AT0001122" IS NULL) AS invalid_line_rows
  FROM {plan} d
  JOIN {month} m ON m."AT0001377" = d."AT0001320" AND m."AT0001361" = 0
  LEFT JOIN {line} l ON l."AT0001122" = m."AT0001358"
    AND l."AT0001230" = d."AT0001321" AND l."AT0001237" = d."AT0001325"
    AND l."AT0001225" = d."AT0001323"
  WHERE d."AT0001329" = 0
  GROUP BY 1, 2, 3, 4
), ship AS (
  SELECT s."AT9200177" AS order_id, s."AT9200169"::date AS ship_date,
         i."AT9200215" AS line_no, i."AT9200213" AS product_id,
         SUM(i."AT9200206") AS qty, SUM(i."AT9200218") AS amount_tax_free,
         COUNT(*) FILTER (WHERE i."AT9200218" IS NULL) AS missing_amount_rows,
         COUNT(*) FILTER (WHERE i."AT9200206" IS NULL OR i."AT9200206" < 0) AS invalid_qty_rows,
         MAX(pr."AT9200243") AS kwh_per_unit
  FROM {shipment} s
  JOIN {item} i ON i."AT9200201" = s."AT9200153" AND i."AT9200225" = 0
  LEFT JOIN {product} pr ON pr."AT9200241" = i."AT9200213"
  WHERE s."AT9200184" = 0 AND s."AT9200169" IS NOT NULL
    AND s."AT9200169"::date BETWEEN %(start)s AND %(end)s {filters}
  GROUP BY 1, 2, 3, 4
), classified AS (
  SELECT s.*, p.plan_rows, p.has_daily_plan, p.planned_qty, p.align_status,
         CASE WHEN p.plan_rows = 1 AND p.invalid_line_rows = 0 AND s.invalid_qty_rows = 0 THEN
           CASE WHEN p.has_daily_plan = '0' THEN s.qty
                WHEN p.has_daily_plan = '1' AND TRIM(p.align_status::text) = '4' AND p.planned_qty IS NOT NULL
                     AND p.planned_qty >= 0 THEN GREATEST(s.qty - p.planned_qty, 0)
                ELSE NULL END
         ELSE NULL END AS outside_qty
  FROM ship s LEFT JOIN plan p ON p.order_id = s.order_id AND p.line_no = s.line_no
    AND p.product_id = s.product_id AND p.plan_date = s.ship_date
)
"""

SC05_AGGREGATE = (
    SC05_BASE
    + """
SELECT COUNT(*) AS actual_rows, COALESCE(SUM(qty), 0) AS actual_qty,
       SUM(qty * kwh_per_unit) / 1000000.0 AS actual_power_gwh,
       COUNT(*) FILTER (WHERE plan_rows > 1) AS ambiguous_rows,
       COUNT(*) FILTER (WHERE outside_qty IS NULL) AS unknown_rows,
       SUM(outside_qty * kwh_per_unit) / 1000000.0 AS outside_power_gwh,
       SUM(amount_tax_free * outside_qty / NULLIF(qty, 0)) / 100000000.0 AS outside_amount_100m,
       COUNT(*) FILTER (WHERE kwh_per_unit IS NULL OR kwh_per_unit <= 0) AS zero_power_rows,
       COALESCE(SUM(missing_amount_rows), 0) AS missing_amount_rows,
       COUNT(*) FILTER (WHERE qty IS NULL OR qty <= 0 OR invalid_qty_rows > 0) AS invalid_qty_rows
FROM classified
"""
)

SC05_ROWS = (
    SC05_BASE
    + """
SELECT *, CASE WHEN plan_rows > 1 THEN 'ambiguous'
               WHEN outside_qty IS NULL THEN 'unknown'
               WHEN outside_qty > 0 THEN 'outside_candidate' ELSE 'within_plan' END AS match_status
FROM classified
ORDER BY outside_qty DESC NULLS LAST, amount_tax_free DESC NULLS LAST, order_id, line_no, product_id, ship_date
LIMIT %(limit)s
"""
)


def query_sc05(catalog: Process360Catalog, scope: Scope, db: Any) -> dict[str, Any]:
    schema = getattr(getattr(db, "config", None), "schema", "ywln_crm")
    filters, params = _filters(
        scope, customer_column='s."AT9200156"', product_column='i."AT9200213"'
    )
    params.update({"start": scope.period_start, "end": scope.period_end, "limit": scope.limit})
    aggregate = db.run(
        SC05_AGGREGATE.format(
            plan=_table(schema, "LE000013"),
            month=_table(schema, "LE000014"),
            line=_table(schema, "LE000011"),
            shipment=_table(schema, "LE000028"),
            item=_table(schema, "LE000031"),
            product=_table(schema, "LE000029"),
            filters=filters,
        ),
        params,
    )
    detail = db.run(
        SC05_ROWS.format(
            plan=_table(schema, "LE000013"),
            month=_table(schema, "LE000014"),
            line=_table(schema, "LE000011"),
            shipment=_table(schema, "LE000028"),
            item=_table(schema, "LE000031"),
            product=_table(schema, "LE000029"),
            filters=filters,
        ),
        params,
    )
    row = (aggregate.rows or [{}])[0]
    actual_power = _number(row.get("actual_power_gwh"))
    unknown = int(row.get("unknown_rows") or 0)
    invalid_qty = int(row.get("invalid_qty_rows") or 0)
    incomplete = bool(unknown or invalid_qty or int(row.get("ambiguous_rows") or 0))
    outside_power = _number(row.get("outside_power_gwh"))
    outside_amount = _number(row.get("outside_amount_100m"))
    if int(row.get("actual_rows") or 0) == 0:
        actual_power = outside_power = outside_amount = 0.0
    classified_outside_power = None if incomplete or row.get("zero_power_rows") else outside_power
    ambiguous = int(row.get("ambiguous_rows") or 0)
    ratio = (
        round(classified_outside_power / actual_power, 6)
        if actual_power is not None
        and actual_power > 0
        and classified_outside_power is not None
        and not row.get("zero_power_rows")
        else None
    )
    status = "blocked" if incomplete else "partial"
    gaps = [
        _query_catalog_gap(catalog, "G12"),
        _query_catalog_gap(catalog, "G13", severity="degrading"),
        _query_catalog_gap(catalog, "G15"),
        _query_catalog_gap(catalog, "G16", severity="degrading"),
    ]
    if incomplete:
        gaps.append(
            gap(
                "PLAN_CLASSIFICATION_UNKNOWN",
                "发货计划匹配或分类不完整",
                needed="唯一关联、有效计划标记/对齐状态、有效发货与计划数量",
                impact="未知记录不视为计划外，不发布正式汇总",
                source="runtime",
            )
        )
    if row.get("missing_amount_rows"):
        gaps.append(
            gap(
                "SHIP_AMOUNT_MISSING",
                "未匹配发货行缺少金额",
                needed="补齐金额与税口径",
                impact="候选金额不能完整计算",
                source="runtime",
            )
        )
    notes = "未匹配记录只是计划外候选，需核查计划标记、例外批准和行映射后才能定性。"
    metrics = [
        metric(
            "M0334",
            _metric_name(catalog, "M0334"),
            _rounded(classified_outside_power),
            "GWh",
            status="blocked" if incomplete or row.get("zero_power_rows") else "partial",
            formula=_metric_formula(catalog, "M0334"),
            evidence="EV10",
            note=notes,
        ),
        metric(
            "M0335",
            _metric_name(catalog, "M0335"),
            None if incomplete or row.get("missing_amount_rows") else outside_amount,
            "亿元",
            status="blocked" if incomplete or row.get("missing_amount_rows") else "partial",
            formula=_metric_formula(catalog, "M0335"),
            evidence="EV10",
            note=notes,
        ),
        metric(
            "M36006",
            _metric_name(catalog, "M36006"),
            ratio,
            "比率",
            status="blocked" if incomplete or ratio is None else "partial",
            formula=_metric_formula(catalog, "M36006"),
            evidence="EV10",
            note="分母为同期间同范围实际发货电量；RF09 目标为空，不能判定达标。",
        ),
    ]
    return envelope(
        "S03",
        status,
        catalog_id=catalog.catalog_id,
        catalog_version=catalog.version,
        scenario="SC05",
        scope=scope,
        metrics=metrics,
        records=detail.rows,
        evidence_items=[
            evidence(
                "EV10",
                "发货与日计划匹配证据",
                source="ywln_crm LE000028/31/13/14/29",
                observed_at=scope.period_end.isoformat(),
                records=detail.rows,
                limitations=[
                    "计划为当前版本，历史期间按当前计划对账",
                    "new_seq 行号映射仍需 G12 验收",
                ],
            )
        ],
        gaps=gaps,
        limitations=[
            "未匹配 != 计划外违规；明确无日计划才取实际数量；已对齐计划按超计划数量计算，未知状态不分类。",
            "先按订单/行/产品/日期汇总，再按计划外数量比例分摊免税金额；不得以含税金额兜底。",
            "计划表无历史快照；当期结果仅代表当前可见计划；历史截止日缺快照则 blocked。",
        ],
        next_steps=["核查未匹配记录的计划与例外凭据", "补充 RF09 目标后才能判断治理效果"],
        queryInfo={
            "aggregateMs": aggregate.duration_ms,
            "detailMs": detail.duration_ms,
            "detailRows": len(detail.rows),
            "totalRows": max(
                int(row.get("overdue_rows") or row.get("actual_rows") or 0), len(detail.rows)
            ),
            "truncated": detail.truncated
            or int(row.get("overdue_rows") or row.get("actual_rows") or 0) > len(detail.rows),
        },
        actualPowerGwh=actual_power,
        outsidePowerGwh=classified_outside_power,
        ambiguousRows=ambiguous,
        unknownRows=unknown,
        zeroPowerRows=int(row.get("zero_power_rows") or 0),
    )


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _rounded(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


SCENARIO_QUERIES = {
    "SC01": query_sc01,
    "SC02": query_sc02,
    "SC03": query_sc03,
    "SC04": query_sc04,
    "SC05": query_sc05,
}


def run_scenario(
    catalog: Process360Catalog, scenario: str, scope: Scope, db: Any
) -> dict[str, Any]:
    code = str(scenario or "").strip().upper()
    query = SCENARIO_QUERIES.get(code)
    if query is None:
        raise ValueError(f"unsupported scenario: {scenario}")
    supported = {
        "SC01": {"customer", "owner", "product"},
        "SC02": {"customer", "owner"},
        "SC03": {"customer"},
        "SC04": {"customer"},
        "SC05": {"customer", "product"},
    }[code]
    unsupported = [
        key
        for key in ("customer", "owner", "product")
        if getattr(scope, key + "_ids") and key not in supported
    ]
    if unsupported:
        return envelope(
            "S03",
            "needs_clarification",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            scope=scope,
            gaps=[
                gap(
                    "UNSUPPORTED_FILTER",
                    "该场景尚无可靠的筛选维度映射",
                    needed=", ".join(unsupported),
                    impact="未执行查询，防止扩大数据范围",
                )
            ],
        )
    if code == "SC05" and scope.observation_cutoff() < date.today():
        return envelope(
            "S03",
            "blocked",
            catalog_id=catalog.catalog_id,
            catalog_version=catalog.version,
            scenario=code,
            scope=scope,
            gaps=[_query_catalog_gap(catalog, "G16")],
            limitations=["历史发货事实不能与当前计划冒充历史计划版本；需提供当时计划快照。"],
        )
    requested = scope
    if code in {"SC01", "SC03", "SC04"} and scope.observation_cutoff() < date.today():
        if not scope.include_current_snapshot:
            return envelope(
                "S03",
                "blocked",
                catalog_id=catalog.catalog_id,
                catalog_version=catalog.version,
                scenario=code,
                scope=scope,
                gaps=[_query_catalog_gap(catalog, "G16")],
                limitations=["当前存量视图无法还原历史时点；未执行查询。"],
            )
        scope = replace(scope, as_of=date.today(), period_end=date.today())
    snapshot = db.snapshot() if hasattr(db, "snapshot") else nullcontext(db)
    with snapshot as reader:
        result = query(catalog, scope, reader)
    if requested != scope:
        result["requestedScope"] = requested.to_dict()
        result["limitations"].append(
            "用户显式选择当前快照；数据观察日已改为今天，不能解释为历史余额。"
        )
    return result
