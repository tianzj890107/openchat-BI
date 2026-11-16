"""Write the 商机获取 ontology version with the gap caliber and AI root causes.

Base:   docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_风险规则及周期SQL修复.xlsx
Output: docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_缺口口径及AI根因版.xlsx

Changes (2026-11-16):

1. Gap risks state target, progress and forecast.  R01 / RK01 and R08 / RK06
   use 缺口 ＝ 目标 −（进度 ＋ 预测）: 进度 is the signed forecast of the months
   before the observation month, 预测 is every forecast from the observation
   month to December.  That is the 全年覆盖预测 branch R03 / R06 already use
   for RK02 / RK05, so all gap risks share one caliber.  R01 and R08 get
   their SQL rebuilt on that branch.
2. Root causes are analysed by the model only.  Every cause's 判定方式 is
   "AI"; BR-C* rules and the cause sheet are an analysis reference, not a
   list to match.  BR-L01 states the global analysis: one model pass over
   every established risk and its metric results, 1–2 causes per risk.
3. Cause review: RC04 / RC06 are reworded (the old names restated the risk
   or used unclear jargon) and the cause ↔ risk links are corrected where a
   cause's scope contradicts or does not explain the risk.

    python scripts/build_opportunity_ai_cause_ontology.py
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_风险规则及周期SQL修复.xlsx"
OUTPUT = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_缺口口径及AI根因版.xlsx"
CHANGE = "2026-11-16缺口口径及AI根因修订"
CELL_LIMIT = 32767

OBSERVED_MONTH = "DATE_TRUNC('MONTH', p.cutoff - INTERVAL '1 MICROSECOND')"
GAP_WORDING = ("缺口＝目标－（进度＋预测）。进度＝观察月以前各月已签单商机预测；预测＝观察当月至12月全部商机预测"
               "（含已签、未签）；进度＋预测即R03明细的全年覆盖预测，取数分支与R03、R06相同（先筛截至观察日可用的预测记录，"
               "再按商机ID＋月份取最新版本）。不混入实际销售额或实际出货量。")

AI_METHOD = "AI"
AI_ACTION = ("AI 全局根因分析：大模型依据本轮已成立风险及其指标结果给出根因；本规则只作分析维度参考，"
             "不做规则命中匹配，结果需复核")

# Reviewed cause ↔ risk links (2026-11-16).  The reason is written into the
# cause sheet so the review stays with the ontology.
CAUSE_RISKS = {
    "RC01": (["RK01", "RK02", "RK03", "RK06", "RK10"],
             "删除RK07：RK07是战略客户无任何商机，不可能同时存在该客户的P0商机"),
    "RC03": (["RK02", "RK05"], "新增RK02：方案推动超期直接拖慢签单进度"),
    "RC04": (["RK05"], ""),
    "RC05": (["RK05"], ""),
    "RC06": (["RK02"],
             "删除RK01：重点跟踪占比反映待签商机的推进管理，解释签单滞后，不解释预测总量低于目标"),
    "RC07": (["RK01", "RK02"],
             "删除RK03：RC07是重点跟踪以外的其余商机，与RK03战略及重点客户范围互斥"),
    "RC08": (["RK01", "RK02", "RK10", "RK11"], ""),
    "RC09": (["RK07"], ""),
    "RC10": (["RK11"], ""),
    "RC11": (["RK11"], ""),
}
RISK_CAUSES = {}
for _cause, (_risks, _) in CAUSE_RISKS.items():
    for _risk in _risks:
        RISK_CAUSES.setdefault(_risk, []).append(_cause)

RC04 = dict(
    name="产品部商机储备与目标不匹配",
    condition=("同一产品部累计实际销售 − 年度目标 < 0（金额、电量分别判断），且该产品部待签商机预测不足以弥补差额："
               "目标分解到产品部后，缺少对应规模的商机储备"),
    focus=("AI 对比产品部年度目标（C03）、累计实际销售（C04）与差距（C05），结合该产品部待签商机预测，"
           "判断缺口是否集中在个别产品部，并说明目标分解与商机储备的错配"),
    rule_name="产品部商机储备与目标不匹配成立判定",
)
RC06 = dict(
    name="待签商机重点跟踪覆盖不足",
    condition=("分母 > 0 且 R04 ÷ R02 < 70%（严格小于；等于 70% 不成立）：战略及重点客户的未签单预测"
               "占全部未签单预测不足七成，多数待签预测未纳入重点跟踪管理"),
    focus=("AI 依据重点跟踪未签单预测（R04）与全部未签单预测（R02）的占比，说明有多少待签预测处于重点跟踪以外，"
           "以及这部分商机推进节奏与资源投入不足对签单进度的影响"),
    rule_name="待签商机重点跟踪覆盖不足成立判定",
)


def clean(value):
    return "" if value is None else str(value).strip()


def header(ws):
    return {clean(cell.value): cell.column for cell in ws[1] if clean(cell.value)}


def rows_by_code(ws):
    found = {}
    for row in range(2, ws.max_row + 1):
        code = clean(ws.cell(row, 1).value)
        if code:
            found[code] = row
    return found


def set_value(ws, row, column, value):
    cols = header(ws)
    if column not in cols:
        raise SystemExit(f"{ws.title} 没有列 {column}")
    if isinstance(value, str) and len(value) > CELL_LIMIT:
        raise SystemExit(f"{ws.title}.{column} 超过 Excel 单元格上限")
    ws.cell(row, cols[column]).value = value


def get_value(ws, row, column):
    return clean(ws.cell(row, header(ws)[column]).value)


def set_code(ws, code, column, value):
    row = rows_by_code(ws).get(code)
    if row is None:
        raise SystemExit(f"{ws.title} 找不到 {code}")
    set_value(ws, row, column, value)


def get_code(ws, code, column):
    row = rows_by_code(ws).get(code)
    if row is None:
        raise SystemExit(f"{ws.title} 找不到 {code}")
    return get_value(ws, row, column)


def append_note(text, note):
    text = clean(text)
    return note if not text or text in {"—", "-"} else (text if note in text else f"{text}；{note}")


def copy_row(ws, source, target):
    for col in range(1, ws.max_column + 1):
        src = ws.cell(source, col)
        dst = ws.cell(target, col)
        dst.value = src.value
        if src.has_style:
            dst._style = copy.copy(src._style)
    if ws.row_dimensions[source].height:
        ws.row_dimensions[target].height = ws.row_dimensions[source].height


# ---- SQL -------------------------------------------------------------------
def annual_prefix(r03_sql):
    """R03's CTE chain through annual_risk_values, without its metric block."""
    marker = "), metric_results AS MATERIALIZED ("
    if r03_sql.count(marker) != 1 or "annual_risk_values AS MATERIALIZED" not in r03_sql:
        raise SystemExit("R03 调用SQL 缺少全年覆盖预测分支，不能派生缺口 SQL")
    return r03_sql.split(marker)[0]


def output_select(r03_sql):
    """The common result projection every metric SQL ends with."""
    marker = "\nSELECT\n  r.code AS \"指标序号\""
    if r03_sql.count(marker) != 1:
        raise SystemExit("R03 调用SQL 的结果列格式与预期不一致")
    return marker + r03_sql.split(marker)[1]


ANNUAL_SPLIT = f"""), annual_risk_split AS MATERIALIZED (
  SELECT
    CASE WHEN GROUPING(f.product_type) = 1 THEN '全部' ELSE f.product_type END AS product_type,
    CASE WHEN COUNT(*) = 0 THEN NULL ELSE COALESCE(SUM(f.amount_yi) FILTER (
      WHERE f.signed AND f.forecast_month < {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) END AS progress_amount,
    CASE WHEN COUNT(*) = 0 THEN NULL ELSE COALESCE(SUM(f.energy_gwh) FILTER (
      WHERE f.signed AND f.forecast_month < {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) END AS progress_energy,
    CASE WHEN COUNT(*) = 0 THEN NULL ELSE COALESCE(SUM(f.amount_yi) FILTER (
      WHERE f.forecast_month >= {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) END AS forecast_amount,
    CASE WHEN COUNT(*) = 0 THEN NULL ELSE COALESCE(SUM(f.energy_gwh) FILTER (
      WHERE f.forecast_month >= {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) END AS forecast_energy
  FROM annual_risk_forecast_facts AS f
  CROSS JOIN context AS p
  GROUP BY GROUPING SETS ((), (f.product_type))
), annual_risk_gaps AS MATERIALIZED (
  SELECT
    v.product_type,
    v.annual_target_amount AS target_amount,
    v.annual_target_energy AS target_energy,
    s.progress_amount, s.progress_energy,
    s.forecast_amount, s.forecast_energy,
    v.annual_coverage_amount AS coverage_amount,
    v.annual_coverage_energy AS coverage_energy,
    v.annual_target_amount - v.annual_coverage_amount AS gap_amount,
    v.annual_target_energy - v.annual_coverage_energy AS gap_energy,
    v.annual_amount_gap_ratio AS gap_rate_amount,
    v.annual_energy_gap_ratio AS gap_rate_energy
  FROM annual_risk_values AS v
  LEFT JOIN annual_risk_split AS s USING (product_type)
"""

R01_RESULTS = """), metric_results AS MATERIALIZED (
  SELECT
    3 AS sort_no,
    CAST('R01' AS TEXT) AS code,
    CAST('商机预测缺口' AS TEXT) AS metric_name,
    CAST(NULL AS TEXT) AS product_team,
    CAST((
      g.gap_amount
    ) AS DECIMAL) AS amount_yi,
    CAST((
      g.gap_energy
    ) AS DECIMAL) AS energy_gwh,
    CAST((
      NULL
    ) AS BIGINT) AS item_count,
    CAST((
      g.gap_rate_amount
    ) AS DECIMAL) AS ratio_value,
    CAST((
      NULL
    ) AS DECIMAL) AS days_value,
    CAST('查询已实现；缺失输入及部分合计见明细' AS TEXT) AS status,
    CAST('缺口＝同口径年度目标－（进度＋预测）；进度＝观察月以前已签单商机预测，预测＝观察月至年底全部商机预测，与R03全年覆盖预测同一分支。金额、电量独立；目标或必要输入缺失时差额NULL，不以0代替未知；比率列为金额缺口率。' AS TEXT) AS note,
    CAST((
      (
        SELECT
          JSONB_AGG(TO_JSONB(v) ORDER BY v.product_type)
        FROM annual_risk_gaps AS v
      )
    ) AS JSONB) AS detail
  FROM annual_risk_gaps AS g
  WHERE
    g.product_type = '全部'
)"""


def r01_sql(r03_sql):
    return annual_prefix(r03_sql) + ANNUAL_SPLIT + R01_RESULTS + output_select(r03_sql)


def r08_sql(r08, r03):
    """R08 on the 进度 + 预测 caliber, keeping its customer scope and output."""
    rows = re.search(r"\), annual_risk_forecast_rows AS MATERIALIZED \(.*?\n\), annual_risk_forecast_facts AS MATERIALIZED \(",
                     r03, flags=re.S)
    if not rows:
        raise SystemExit("R03 调用SQL 缺少 annual_risk_forecast_rows")
    rows_cte = rows.group(0)[len("), "):-len("\n), annual_risk_forecast_facts AS MATERIALIZED (")]
    customer_forecast = re.search(
        r"\), customer_forecast AS MATERIALIZED \(\n.*?\n\), customer_gaps AS MATERIALIZED \(", r08, flags=re.S)
    if not customer_forecast:
        raise SystemExit("R08 调用SQL 缺少 customer_forecast")
    replacement = (
        "), " + rows_cte + "\n"
        "), customer_forecast AS MATERIALIZED (\n"
        "  SELECT\n"
        "    o.account_id,\n"
        "    o.product_type,\n"
        f"    COALESCE(SUM(f.amount_yuan / CAST(100000000 AS DECIMAL)) FILTER (\n"
        f"      WHERE o.signed AND f.forecast_month < {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) AS progress_amount,\n"
        f"    COALESCE(SUM(f.amount_yuan / NULLIF(f.wh_price, 0) / CAST(1000000000 AS DECIMAL)) FILTER (\n"
        f"      WHERE o.signed AND f.forecast_month < {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) AS progress_energy,\n"
        f"    COALESCE(SUM(f.amount_yuan / CAST(100000000 AS DECIMAL)) FILTER (\n"
        f"      WHERE f.forecast_month >= {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) AS forecast_amount,\n"
        f"    COALESCE(SUM(f.amount_yuan / NULLIF(f.wh_price, 0) / CAST(1000000000 AS DECIMAL)) FILTER (\n"
        f"      WHERE f.forecast_month >= {OBSERVED_MONTH}), CAST(0 AS DECIMAL)) AS forecast_energy\n"
        "  FROM annual_risk_forecast_rows AS f\n"
        "  JOIN opportunity_flags AS o\n"
        "    USING (opportunity_id)\n"
        "  CROSS JOIN context AS p\n"
        "  WHERE\n"
        "    f.rn = 1\n"
        "  GROUP BY\n"
        "    o.account_id,\n"
        "    o.product_type\n"
        "), customer_gaps AS MATERIALIZED ("
    )
    sql = r08.replace(customer_forecast.group(0), replacement)
    old_select = re.search(r"  t\.target_amount,\n  f\.forecast_amount,\n.*?AS gap_energy\n", sql, flags=re.S)
    if not old_select:
        raise SystemExit("R08 customer_gaps 结果列与预期不一致")
    sql = sql.replace(old_select.group(0), (
        "  t.target_amount,\n"
        "  f.progress_amount,\n"
        "  f.forecast_amount,\n"
        "  f.progress_amount + f.forecast_amount AS coverage_amount,\n"
        "  t.target_amount - (f.progress_amount + f.forecast_amount) AS gap_amount,\n"
        "  t.target_energy,\n"
        "  f.progress_energy,\n"
        "  f.forecast_energy,\n"
        "  f.progress_energy + f.forecast_energy AS coverage_energy,\n"
        "  t.target_energy - (f.progress_energy + f.forecast_energy) AS gap_energy\n"
    ))
    sql = sql.replace(
        "CAST('仅储能客户名单内，按客户ID＋产品类型对齐年度目标与所选期间预测，分别计算目标－预测。",
        "CAST('仅储能客户名单内，按客户ID＋产品类型对齐年度目标与进度＋预测，分别计算目标－（进度＋预测）；"
        "进度＝观察月以前已签单商机预测，预测＝观察月至年底全部商机预测，与R03全年覆盖预测同一分支。")
    if "目标－（进度＋预测）" not in sql:
        raise SystemExit("R08 取值说明未更新")
    return sql


def check_sql(sql, label):
    try:
        import pglast
    except ImportError:  # pragma: no cover - optional authoring check
        print(f"跳过 {label} 语法检查（未安装 pglast）")
        return
    pglast.parse_sql(sql)


# ---- workbook edits ----------------------------------------------------------
def edit_metrics(book):
    ws = book["指标"]
    r03 = get_code(ws, "R03", "调用SQL")
    sql01 = r01_sql(r03)
    check_sql(sql01, "R01")
    set_code(ws, "R01", "调用SQL", sql01)
    set_code(ws, "R01", "调用SQL依赖CTE数", 27)
    set_code(ws, "R01", "调用SQL依赖CTE", get_code(ws, "R03", "调用SQL依赖CTE")
             + " → annual_risk_split → annual_risk_gaps")
    set_code(ws, "R01", "指标定义",
             "B01 年度目标 −（进度＋预测）。" + GAP_WORDING + "金额、电量分别计算，并输出缺口率＝缺口÷目标。")
    set_code(ws, "R01", "业务规则",
             "缺口大于 0，即判为商机全年覆盖（进度＋预测）不足；等级按缺口率。目标缺失或为 0 时缺口率保持 NULL。")
    set_code(ws, "R01", "结果列", "金额_亿元、电量_GWh、比率_原始小数")
    set_code(ws, "R01", "V3变更", append_note(get_code(ws, "R01", "V3变更"), CHANGE + "：缺口改为目标－（进度＋预测）"))

    sql08 = r08_sql(get_code(ws, "R08", "调用SQL"), r03)
    check_sql(sql08, "R08")
    set_code(ws, "R08", "调用SQL", sql08)
    set_code(ws, "R08", "调用SQL依赖CTE", get_code(ws, "R08", "调用SQL依赖CTE").replace(
        "forecast_facts → customer_forecast", "forecast_facts → annual_risk_forecast_rows → customer_forecast"))
    set_code(ws, "R08", "调用SQL依赖CTE数", 22)
    set_code(ws, "R08", "指标定义",
             "仅储能客户名单内，按客户ID＋产品类型对齐年度目标与进度＋预测，分别计算目标－（进度＋预测）。"
             + GAP_WORDING + "客户没有商机也可在名单中；目标版本、金额/电量单位及单侧缺失NULL规则沿本文件。")
    set_code(ws, "R08", "V3变更", append_note(get_code(ws, "R08", "V3变更"), CHANGE + "：客户缺口改为目标－（进度＋预测）"))


def edit_risks(book):
    ws = book["风险"]
    set_code(ws, "RK01", "风险描述", "商机全年覆盖（进度＋预测）低于年度目标，存在缺口")
    set_code(ws, "RK01", "成立条件",
             "R01 缺口＝年度目标－（进度＋预测）> 0 成立（金额、电量分别判断）；进度＝观察月以前已签单商机预测，"
             "预测＝观察当月至12月全部商机预测")
    set_code(ws, "RK06", "风险描述", "有商机客户的进度＋预测低于客户目标")
    set_code(ws, "RK06", "成立条件", "有商机且 R08 缺口＝客户目标－（进度＋预测）> 0")
    for code, causes in RISK_CAUSES.items():
        set_code(ws, code, "候选根因", "、".join(causes))
    present = set(rows_by_code(ws))
    missing = present - set(RISK_CAUSES)
    if missing:
        raise SystemExit(f"风险 {sorted(missing)} 没有复核后的根因关联")


def edit_rules(book):
    ws = book["业务规则"]
    set_code(ws, "BR-A01", "规则描述", "商机全年覆盖（进度＋预测）低于年度目标。" + GAP_WORDING)
    set_code(ws, "BR-A01", "判断或结果",
             "R01 缺口＝目标－（进度＋预测）> 0 成立（金额、电量分别判断）；等级：缺口率 ≥ 10% 高；5%~10% 中；< 5% 低")
    set_code(ws, "BR-A06", "规则描述",
             "仅在储能客户名单内适用。有商机客户的进度＋预测低于客户目标；进度、预测口径同R01")
    set_code(ws, "BR-A06", "判断或结果",
             "储能客户按BR-Q04范围筛选。有商机且 R08 缺口＝客户目标－（进度＋预测）> 0；等级：战略客户 高；其他 中")
    for code in rows_by_code(ws):
        if code.startswith("BR-C"):
            set_code(ws, code, "处置动作", AI_ACTION)
    set_code(ws, "BR-C04", "规则名称", RC04["rule_name"])
    set_code(ws, "BR-C04", "判断或结果", RC04["condition"])
    set_code(ws, "BR-C04", "关联本体元素", "根因：RC04 " + RC04["name"])
    set_code(ws, "BR-C06", "规则名称", RC06["rule_name"])
    set_code(ws, "BR-C06", "判断或结果", RC06["condition"])
    set_code(ws, "BR-C06", "关联本体元素", "根因：RC06 " + RC06["name"])
    set_code(ws, "BR-L01", "规则名称", "AI 全局根因分析")
    set_code(ws, "BR-L01", "规则描述",
             "对本轮全部已成立风险做一次大模型全局分析：输入只含各风险的判定结果与其指标取值，"
             "模型为每条风险给出最可能的根因；分析维度由模型依据数据自行确定，不从根因库匹配或套用已有根因")
    set_code(ws, "BR-L01", "触发条件", "风险判定完成后")
    set_code(ws, "BR-L01", "判断或结果",
             "每条已成立风险输出 1～2 条根因（名称、分析依据、需补充核实的数据）；引用数字必须来自输入的指标结果（BR-D02）；"
             "根因均为 AI 分析结论，标注待核实")
    set_code(ws, "BR-L01", "关联本体元素", "风险：RK01、RK02、RK03、RK05、RK06、RK07、RK10、RK11")


def edit_causes(book):
    ws = book["根因"]
    for code, row in rows_by_code(ws).items():
        set_value(ws, row, "判定方式", AI_METHOD)
        risks, reason = CAUSE_RISKS[code]
        set_value(ws, row, "关联风险", "、".join(risks))
        if reason:
            set_value(ws, row, "AI 分析要点", append_note(get_value(ws, row, "AI 分析要点"), "关联复核：" + reason))
    set_code(ws, "RC04", "根因名称", RC04["name"])
    set_code(ws, "RC04", "成立条件", RC04["condition"])
    set_code(ws, "RC04", "AI 分析要点", RC04["focus"])
    set_code(ws, "RC06", "根因名称", RC06["name"])
    set_code(ws, "RC06", "成立条件", RC06["condition"])
    set_code(ws, "RC06", "AI 分析要点", RC06["focus"] + "；关联复核：" + CAUSE_RISKS["RC06"][1])
    ws = book["行动建议"]
    for code, row in rows_by_code(ws).items():
        cause = get_value(ws, row, "对应根因")
        if cause == "RC04":
            set_value(ws, row, "根因名称", RC04["name"])
        elif cause == "RC06":
            set_value(ws, row, "根因名称", RC06["name"])


def edit_chain(book):
    ws = book["指标-风险-根因-行动建议链路"]
    cols = header(ws)
    keep = []
    removed = []
    for row in range(2, ws.max_row + 1):
        risk = clean(ws.cell(row, cols["风险编码"]).value)
        cause = clean(ws.cell(row, cols["根因编码"]).value)
        if not risk:
            continue
        if cause not in RISK_CAUSES.get(risk, []):
            removed.append((clean(ws.cell(row, 1).value), risk, cause))
            continue
        keep.append(row)
    rk02 = next(row for row in keep if clean(ws.cell(row, cols["风险编码"]).value) == "RK02")
    rc03 = next(row for row in keep if clean(ws.cell(row, cols["根因编码"]).value) == "RC03")
    values = [[ws.cell(row, col).value for col in range(1, ws.max_column + 1)] for row in keep]
    styles = [row for row in keep]
    # RK02 → RC03 (new): the risk side of an RK02 row, the cause side of an RC03 row.
    risk_cols = ("触发指标", "异常判定规则", "风险编码", "风险名称", "风险成立条件")
    new = [ws.cell(rc03, col).value for col in range(1, ws.max_column + 1)]
    for name in risk_cols:
        new[cols[name] - 1] = ws.cell(rk02, cols[name]).value
    new[0] = "L035"
    insert_at = max(index for index, row in enumerate(keep)
                    if clean(ws.cell(row, cols["风险编码"]).value) == "RK02") + 1
    values.insert(insert_at, new)
    styles.insert(insert_at, rc03)
    snapshot = {row: [copy.copy(ws.cell(row, col)._style) for col in range(1, ws.max_column + 1)]
                for row in set(styles)}
    heights = {row: ws.row_dimensions[row].height for row in set(styles)}
    last = ws.max_row
    for index, (row_values, style_row) in enumerate(zip(values, styles), start=2):
        for col, value in enumerate(row_values, start=1):
            cell = ws.cell(index, col)
            cell.value = value
            cell._style = copy.copy(snapshot[style_row][col - 1])
        ws.row_dimensions[index].height = heights[style_row]
    for row in range(len(values) + 2, last + 1):
        for col in range(1, ws.max_column + 1):
            ws.cell(row, col).value = None
    for row in range(2, len(values) + 2):
        ws.cell(row, cols["判定方式"]).value = AI_METHOD
        cause = clean(ws.cell(row, cols["根因编码"]).value)
        if cause == "RC04":
            ws.cell(row, cols["根因名称"]).value = RC04["name"]
            ws.cell(row, cols["根因成立规则"]).value = "BR-C04"
        elif cause == "RC06":
            ws.cell(row, cols["根因名称"]).value = RC06["name"]
    for label, risk_code in (("RK01", "RK01"), ("RK06", "RK06")):
        condition = get_code(book["风险"], risk_code, "成立条件")
        for row in range(2, len(values) + 2):
            if clean(ws.cell(row, cols["风险编码"]).value) == label:
                ws.cell(row, cols["风险成立条件"]).value = condition
    return removed, len(values)


def edit_notes(book, removed, chain_count):
    ws = book["说明"]
    rows = {clean(ws.cell(row, 1).value): row for row in range(1, ws.max_row + 1)}
    ws.cell(rows["链路"], 2).value = (
        "源数据（ded_public）→ 指标 → 指标异常（业务规则 BR-A*）→ 风险 → AI 全局根因分析（大模型依据已成立风险及其指标结果，"
        "每条风险给出 1～2 条根因；BR-C* 与根因表只作分析维度参考，不做匹配）→ 根因 → 行动建议 → 任务令（人工确认下发）")
    target = ws.max_row + 1
    copy_row(ws, rows["本次风险修订"], target)
    ws.cell(target, 1).value = "本次缺口及根因修订"
    ws.cell(target, 2).value = (
        f"{CHANGE}。①缺口类风险统一给出目标、进度、预测与缺口：RK01（R01）、RK06（R08）改为缺口＝目标－（进度＋预测），"
        "与RK05（R06）、RK02全年覆盖预测同一分支；R01、R08调用SQL按该分支重写。②根因全部改为 AI 判定：根因表“判定方式”及链路"
        "“判定方式”统一为AI，BR-C*处置动作改为AI分析参考，BR-L01改为AI全局根因分析（每条已成立风险1～2条根因，不匹配根因库）。"
        f"③根因复核：RC04改名“{RC04['name']}”（原“产品部销售缺口”用缺口解释缺口）；RC06改名“{RC06['name']}”"
        "（原“承接不足”表意不清）；关联修正：" + "；".join(
            f"{code}：{reason}" for code, (_, reason) in CAUSE_RISKS.items() if reason)
        + "。链路删除 " + "、".join(f"{lid}（{risk}—{cause}）" for lid, risk, cause in removed)
        + f"，新增 L035（RK02—RC03），现有完整链路 {chain_count} 条。")
    return target


def main():
    book = openpyxl.load_workbook(BASE)
    edit_metrics(book)
    edit_risks(book)
    edit_rules(book)
    edit_causes(book)
    removed, chain_count = edit_chain(book)
    edit_notes(book, removed, chain_count)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    book.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)}  removed={removed} chain={chain_count}")


if __name__ == "__main__":
    main()
