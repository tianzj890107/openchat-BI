"""Generate the 销售额／出货量共同问题分析 ontology workbook.

Inputs (all read-only):
  - reference ontology: 亿纬锂能_本体_商机获取节点_V3_无投标_周期红字同步版.xlsx
  - data dictionary:    ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx
  - metric list:        bp_local_analysis_query_202611141015.csv
Output:
  - docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V1.xlsx
"""
import csv
import hashlib
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
REF = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_无投标_周期红字同步版.xlsx"
DICT = ROOT / "docs/亿纬锂能/ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx"
CSV = ROOT / "bp_local_analysis_query_202611141015.csv"
OUT = ROOT / "docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V2.xlsx"

PERIOD_START, PERIOD_END = "2025-01-01", "2026-01-01"
NODE = "销售额／出货量共同问题分析"
PENDING = "（建议值·待业务确认）"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sheet_rows(wb, name):
    rows = [r for r in wb[name].iter_rows(values_only=True) if r and any(c is not None for c in r)]
    header = [str(c) if c is not None else "" for c in rows[0]]
    return header, [list(r[:len(header)]) + [None] * (len(header) - len(r)) for r in rows[1:]]


# ---------------------------------------------------------------- inputs
ref = openpyxl.load_workbook(REF, read_only=True)
dic = openpyxl.load_workbook(DICT, read_only=True)
csv.field_size_limit(10 ** 9)
queries = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))


def q_metrics(r):
    return [c["identifierCode"] for c in json.loads(r["columns"]) if c.get("type") != "DIMENSION"]


def q_dims(r):
    return [c["identifierCode"] for c in json.loads(r["columns"]) if c.get("type") == "DIMENSION"]


def q_label(r, code):
    return next(c["label"] for c in json.loads(r["columns"]) if c["identifierCode"] == code)


def pick_query(code, prefer_dims=None):
    cands = [r for r in queries if r["query_type"] == "METRIC" and code in q_metrics(r)]
    if not cands:
        raise SystemExit(f"指标清单中找不到 {code}")
    if prefer_dims is not None:
        exact = [r for r in cands if q_dims(r) == prefer_dims]
        if exact:
            cands = exact
    cands.sort(key=lambda r: (len(q_dims(r)), len(q_metrics(r)), r["query_key"]))
    return cands[0]


PARAMS_CTE = (f"parameters AS (SELECT DATE '{PERIOD_START}' AS start_date, "
              f"DATE '{PERIOD_END}' AS end_exclusive, "
              f"CAST(CURRENT_TIMESTAMP AS TIMESTAMP) AS observed_at)")


CELL_LIMIT = 32000  # Excel keeps at most 32,767 characters per cell


def compact(text):
    """Drop line indentation, trailing blanks and empty lines; SQL meaning is unchanged."""
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def fit_cell(text, *, what, key):
    if len(text) <= CELL_LIMIT:
        return text
    small = compact(text)
    if len(small) <= CELL_LIMIT:
        return small
    return f"（{what}原文 {len(text)} 字符，超过 Excel 单元格上限，未写入；见指标清单 query_key：{key}）"


def render_sql(sql):
    """Turn a dashboard SQL template into a directly executable statement."""
    s = re.sub(r"/\*FILTER_BEGIN:([A-Za-z0-9_]+)\*/.*?/\*FILTER_END:\1\*/", "", sql, flags=re.S)
    s = s.replace("/*TIME_BEGIN*/", "").replace("/*TIME_END*/", "")
    s = re.sub(r"(?<!:):start_date\b", "(SELECT start_date FROM parameters)", s)
    s = re.sub(r"(?<!:):end_exclusive\b", "(SELECT end_exclusive FROM parameters)", s)
    # The dashboard reads "now" inline; the ontology makes the observation
    # time an explicit parameter so a run can be reproduced.
    s = re.sub(r"\bCURRENT_TIMESTAMP\b|\bNOW\(\)|\bLOCALTIMESTAMP\b",
               "(SELECT observed_at FROM parameters)", s, flags=re.I)
    s = re.sub(r"\bCURRENT_DATE\b", "(SELECT observed_at FROM parameters)::date", s, flags=re.I)
    leftover = sorted(set(re.findall(r"(?<![:\w]):([a-z_]+)\b", re.sub(r"'[^']*'", "''", s))))
    if leftover:
        raise SystemExit(f"渲染后仍有未绑定参数：{leftover}")
    s = s.strip()
    while s.startswith("--"):
        s = s.split("\n", 1)[1].lstrip() if "\n" in s else ""
    s = re.sub(r"\n\s*\n+", "\n", s)
    if re.match(r"WITH\s+RECURSIVE\b", s, re.I):
        s = re.sub(r"^WITH\s+RECURSIVE\b", "WITH RECURSIVE " + PARAMS_CTE + ",", s, count=1, flags=re.I)
    elif re.match(r"WITH\b", s, re.I):
        s = re.sub(r"^WITH\b", "WITH " + PARAMS_CTE + ",", s, count=1, flags=re.I)
    else:
        s = "WITH " + PARAMS_CTE + "\n" + s
    header = (f"-- {NODE} · 调用SQL（由看板查询模板渲染）；PostgreSQL 只读；无绑定参数。\n"
              f"-- 改统计期间只改 parameters 的 start_date / end_exclusive；observed_at 为观察时点（默认当前时间）；"
              f"可选筛选已去除（全量口径）。\n")
    if len(header + s) > CELL_LIMIT:
        s = compact(s)
        if len(header + s) > CELL_LIMIT:
            raise SystemExit(f"调用SQL 去缩进后仍超过单元格上限：{len(header + s)}")
    return header + s


# ---------------------------------------------------------------- business layer (from reference)
KEEP_LE = ["LE01", "LE02", "LE04", "LE05", "LE06", "LE07", "LE08", "LE10", "LE11", "LE12",
           "LE13", "LE16", "LE17", "LE18"]
NEW_LE = OrderedDict([
    ("LE19", dict(name="订单日出货管理", en="shipmentDetail", sheet="订单日出货管理",
                  table="ded_public.p_fm_edw_v_ods_crm_new_shipmentdetail_esb", crm="new_shipmentdetail",
                  pk="new_shipmentdetailid",
                  definition="订单行按日的出货计划与实际出货数量；计划外发货（M0151）的计划侧来源。")),
    ("LE20", dict(name="日出货计划月度信息", en="shipmentPlanMonth", sheet="日出货计划月度信息",
                  table="ded_public.p_fm_edw_v_ods_crm_new_shipmentdetail_monthinfo_esb",
                  crm="new_shipmentdetail_monthinfo", pk="new_shipmentdetail_monthinfoid",
                  definition="日出货计划按月的版本信息（交付计划变更次数、修改时间），用于判定计划是否在出货前生效。")),
])

bo_header, bo_rows = sheet_rows(ref, "业务对象")
bo_rows = [r for r in bo_rows if r[0] in {"BO01", "BO02", "BO03", "BO04", "BO06", "BO07"}]
for r in bo_rows:
    if r[0] == "BO04":
        r[3] = ("订单、订单产品、发货单及日出货计划：订单接收、订单履约、订未发（正常 / 超期）、"
                "已发货与计划外发货的事实来源；销售额实绩与出货量实绩均来自发货明细。")
    if r[0] == "BO01":
        r[3] = "销售机会及其月度销售预测、项目进展；本卡片用于上游商机覆盖、签单转化与项目卡点下钻。"
bor_header, bor_rows = sheet_rows(ref, "对象关系")
bo_codes = {r[0] for r in bo_rows}
bor_rows = [r for r in bor_rows if r[1] in bo_codes and r[6] in bo_codes]

le_header, le_rows = sheet_rows(ref, "逻辑实体")
le_rows = [r for r in le_rows if r[2] in KEEP_LE]
for code, spec in NEW_LE.items():
    le_rows.append(["BO04", "订单与发货", code, spec["name"], spec["en"], spec["definition"], "N",
                    "源数据（ded_public）"])

lem_header, lem_rows = sheet_rows(ref, "逻辑实体映射")
lem_rows = [r for r in lem_rows if r[0] in KEEP_LE]
for code, spec in NEW_LE.items():
    lem_rows.append([code, spec["name"], spec["en"], spec["table"], spec["crm"], "05 交付", "已存在"])
TABLE_TO_LE = {}
for r in lem_rows:
    m = re.search(r"(p_fm_edw_v_ods_crm_[a-z0-9_]+)", str(r[3] or ""))
    if m:
        TABLE_TO_LE[m.group(1)] = r[0]
LE_NAME = {r[2]: r[3] for r in le_rows}

attr_header, attr_rows = sheet_rows(ref, "业务属性")
attr_rows = [r for r in attr_rows if r[0] in KEEP_LE]
map_header, map_rows = sheet_rows(ref, "业务属性映射")
map_rows = [r for r in map_rows if r[0] in KEEP_LE]

for code, spec in NEW_LE.items():
    raw = [r for r in dic[spec["sheet"]].iter_rows(values_only=True)]
    seq = 0
    for r in raw[2:]:
        if not r or not r[0]:
            continue
        seq += 1
        field, display, dtype, desc, options, lookup, _, required, _, dbtype, _ = (list(r) + [None] * 11)[:11]
        acode = f"{code}-A{seq:04d}"
        sample = str(desc) if desc and "实测抽样" in str(desc) else "字典未统计"
        attr_rows.append([code, spec["name"], acode, display or field, field, desc or "", dtype or "",
                          dbtype or "", options or "", lookup or "",
                          "Y" if field == spec["pk"] else "N",
                          "Y" if str(required or "").lower() in {"required", "applicationrequired", "systemrequired"} else "N",
                          sample, "N"])
        map_rows.append([code, spec["name"], acode, display or field, field, spec["table"], field, "直接映射"])

ATTR_BY_EN = defaultdict(dict)
for r in attr_rows:
    ATTR_BY_EN[r[0]][str(r[4])] = r

er_header, er_rows = sheet_rows(ref, "实体关系")
kept_le = set(KEEP_LE) | set(NEW_LE)
er_rows = [r for r in er_rows if r[1] in kept_le and r[3] in kept_le]


def acode(le, en):
    row = ATTR_BY_EN[le].get(en)
    if not row:
        raise SystemExit(f"实体关系引用的属性不存在：{le}.{en}")
    return row[2]


def er(code, src, dst, kind, name, card, s_en, d_en, desc):
    return [code, src, LE_NAME[src], dst, LE_NAME[dst], kind, name, card,
            acode(src, s_en), s_en, acode(dst, d_en), d_en, desc]


er_rows += [
    er("ER22", "LE07", "LE16", "关联关系", "订单生成发货单", "1:N", "salesorderid", "new_salesorderid",
       "发货单 new_salesorderid 指向订单；实际销售额 M0001 经此取订单与商机属性"),
    er("ER23", "LE07", "LE19", "关联关系", "订单排定日出货计划", "1:N", "salesorderid", "new_salesorder_id",
       "日出货计划 new_salesorder_id 指向订单；计划外发货按订单＋行号＋产品＋日期对齐计划与实际"),
    er("ER24", "LE20", "LE19", "组合关系", "月度计划包含日出货计划", "1:N",
       "new_shipmentdetail_monthinfoid", "new_shipmentdetail_monthinfoid",
       "月度计划修改时间晚于出货日视为计划未生效，计入计划问题"),
    er("ER25", "LE18", "LE19", "关联关系", "产品物料对应日出货计划", "1:N", "productid", "new_product_id",
       "按产品主键关联日出货计划与产品物料"),
    er("ER26", "LE05", "LE16", "关联关系", "客户接收发货", "1:N", "accountid", "new_account_id",
       "发货单 new_account_id 指向客户；客户维度筛选与客户电量缺口使用"),
]

run_header, run_rows = sheet_rows(ref, "分析运行记录模型")
RUN_TERMS = [("风险运行记录", "问题运行记录"), ("风险影响明细", "问题影响明细"), ("riskInstance", "issueInstance"),
             ("riskImpact", "issueImpact"), ("risk_instance", "issue_instance"), ("risk_impact", "issue_impact"),
             ("风险 RK*", "问题 IS* / DQ*"), ("某统计期间成立的风险", "某统计期间成立的问题（指标异常 / 数据问题）"),
             ("风险实例", "问题实例"), ("风险编码", "问题编码"), ("风险名称", "问题名称"), ("风险等级", "问题等级"),
             ("risk_code", "issue_code"), ("risk_level", "issue_level"), ("risk_name", "issue_name")]
for r in run_rows:
    for i, v in enumerate(r):
        if isinstance(v, str):
            for old, new in RUN_TERMS:
                v = v.replace(old, new)
            r[i] = (v.replace("受影响的商机 / 客户 / 产品部及预测量",
                              "受影响的订单 / 客户 / 产品团队 / 产品类型及金额、电量")
                     .replace("对象类型（商机 / 客户 / 产品部）", "对象类型（订单 / 客户 / 产品团队 / 产品类型 / 商机）"))

# ---------------------------------------------------------------- metrics
# (code, name, group, kind, unit, dashboard code, prefer dims, definition, rule, time dim, dims)
M = OrderedDict()


def metric(code, name, group, kind, unit, board=None, prefer=None, definition="", rule="",
           time="通用统计期间（D044）", dims="D003、D004、D005、D006", derived=None):
    M[code] = dict(code=code, name=name, group=group, kind=kind, unit=unit, board=board, prefer=prefer,
                   definition=definition, rule=rule, time=time, dims=dims, derived=derived)


metric("B01", "目标销售额", "基础", "原子指标", "亿元", "YWLN_M0002",
       definition="所选年度销售目标金额汇总（人民币元 ÷ 10^8）。",
       rule="目标先按商机 ID＋年度去重取最新版本再汇总（BR-Q03）；销售额达成率与预计达成率的分母。",
       time="目标年度")
metric("B02", "实际销售额", "基础", "原子指标", "亿元", "YWLN_M0001",
       definition="所选期间发货明细金额 new_amount_base 汇总（÷ 10^8），按发货单 new_shipping2_date 归期，仅数量 > 0 的发货行。",
       rule="销售额实绩口径（BR-Q01）；与出货量实绩同一发货事实来源。")
metric("B03", "目标出货量", "基础", "原子指标", "GWh", "YWLN_M0007",
       definition="所选年度目标出货电量：目标 new_month1_power～12_power 按 kWh ÷ 10^6 换算 GWh。",
       rule="目标去重与电量换算按 BR-Q03（kWh ÷ 10^6）。", time="目标年度")
metric("B04", "实际出货量", "基础", "原子指标", "GWh", "YWLN_M0006",
       definition="所选期间已发货数量 × 产品单套电量（kWh）÷ 10^6，按发货日期归期。",
       rule="出货量实绩口径（BR-Q02）。")
metric("B05", "年度时间消耗", "基础", "原子指标", "比值", "YWLN_M0009",
       definition="所选年度已过天数 ÷ 全年天数（0～1）。", rule="达成率与时间进度比较的基准（BR-Q06）。",
       time="统计截止日", dims="—")
metric("R01", "销售额达成率", "风险", "复合指标", "%", "YWLN_M0003",
       definition="B02 实际销售额 ÷ B01 目标销售额。", rule="与 B05 比较判定销售额进度（BR-A01）。")
metric("R02", "出货量达成率", "风险", "复合指标", "比值", "YWLN_M0008",
       definition="B04 实际出货量 ÷ B03 目标出货量。", rule="与 B05 比较判定出货进度（BR-A01）。")
metric("R03", "销售额与出货量达成率差", "风险", "派生指标", "百分点",
       definition="R01 销售额达成率 − R02 出货量达成率（统一换算为百分比后相减）。",
       rule="绝对值超过阈值判定量价背离（BR-A03）；正值表示金额进度快于电量，负值反之。",
       derived="R01、R02")
metric("R04", "预计销售额", "风险", "复合指标", "亿元", "YWLN_M0004",
       definition="已历月份取实际销售额，当月及以后取商机月度预测销售额。",
       rule="全年预计达成判定的分子（BR-A02）；与商机获取节点 B02（只用预测金额）口径不同，见说明“与商机卡片差异”。")
metric("R05", "预计销售额达成率", "风险", "复合指标", "%", "YWLN_M0005",
       definition="R04 预计销售额 ÷ B01 目标销售额。", rule="< 100% 判定全年销售额预计不达成（BR-A02）。")
metric("R06", "预计出货量", "风险", "复合指标", "GWh", "YWLN_M0011",
       definition="已发货电量＋当月及以后预测出货电量。", rule="全年预计达成判定的分子（BR-A02）。")
metric("R07", "预计出货量达成率", "风险", "复合指标", "比值", "YWLN_M0012",
       definition="R06 预计出货量 ÷ B03 目标出货量。", rule="< 1 判定全年出货量预计不达成（BR-A02）。")
metric("R08", "还可出货量", "风险", "复合指标", "GWh", "YWLN_M0010",
       definition="看板“还可出货量”：当月及以后商机月度预测可出货电量。",
       rule="与剩余目标比较，作为 RK05 的补充证据。")
metric("R09", "实际单位电量销售额", "风险", "派生指标", "元/Wh",
       definition="B02 × 10^8 ÷ (B04 × 10^9)，即实际每 Wh 销售额。", rule="与 R10 比较判定单价或产品结构偏离（BR-C06）。",
       derived="B02、B04")
metric("R10", "目标单位电量销售额", "风险", "派生指标", "元/Wh",
       definition="B01 × 10^8 ÷ (B03 × 10^9)，即目标隐含每 Wh 销售额。", rule="R09 的比较基准（BR-C06）。",
       time="目标年度", derived="B01、B03")
metric("O01", "订单接收电量", "订单", "原子指标", "GWh", "YWLN_M0032", prefer=["YWLN_D003"],
       definition="所选期间 OA 审批通过的有效订单行电量，按产品类型分组。",
       rule="有效订单口径（BR-Q04）；计算取消 / 变更占比的分母。", dims="D003")
metric("O02", "订单接收金额", "订单", "原子指标", "亿元", "YWLN_M0033", prefer=["YWLN_D016"],
       definition="订单接收金额，按订单状态（正常订单 / 订单变更 / 订单取消）分组。",
       rule="订单状态取自 D016；取消包括系统状态 2 及已审批生效的取消变更。", dims="D016")
metric("O03", "订单履约率", "订单", "复合指标", "比值", "YWLN_M0037",
       definition="按订单审批期间选有效已签订单，累计截至期末的已发货明细金额 ÷ 该批订单金额；取消订单两侧同排除。",
       rule="低于阈值判定履约不足（BR-A06）。")
metric("O04", "取消／变更订单电量", "订单", "原子指标", "GWh", "YWLN_M_ORDER_CANCEL_CHANGE",
       definition="所选期间取消或变更订单涉及的电量。", rule="> 0 判定订单冲减（BR-A08）。")
metric("O05", "订单接收平均周期", "订单", "原子指标", "天", "YWLN_M0053",
       definition="订单接收环节平均办理天数。", rule="与 O06 比较，作为签单转化滞后的辅助证据。")
metric("O06", "订单接收标杆周期", "订单", "原子指标", "天", "YWLN_M0054",
       definition="订单接收环节标杆天数。", rule="O05 的比较基准。")
metric("S01", "已发货电量", "发货", "原子指标", "GWh", "YWLN_M0144",
       definition="有效订单下已发货电量。", rule="与未发货电量构成订单发货结构。")
metric("S02", "已发货金额", "发货", "原子指标", "亿元", "YWLN_M0148",
       definition="有效订单下已发货金额。", rule="与未发货金额构成订单发货结构。")
metric("S03", "未发货电量", "发货", "原子指标", "GWh", "YWLN_M0145",
       definition="有效订单下尚未发货的电量（订未发电量）。", rule="剩余目标订单覆盖率（电量）的分子（C09）。")
metric("S04", "未发货金额", "发货", "原子指标", "亿元", "YWLN_M0149",
       definition="有效订单下尚未发货的金额（订未发金额）。", rule="剩余目标订单覆盖率（金额）的分子（C09）。")
metric("S05", "超期订未发金额", "发货", "原子指标", "亿元", "YWLN_M0143",
       definition="承诺交期（订单产品 requestdeliveryby）早于统计截止日仍未发货的金额。",
       rule="超期判定 BR-Q05；> 0 为 RK04 前提。")
metric("S06", "超期订未发电量", "发货", "原子指标", "GWh", "M0134",
       definition="承诺交期早于统计截止日仍未发货的电量。", rule="超期判定 BR-Q05。")
metric("S07", "正常订未发金额", "发货", "原子指标", "亿元", "YWLN_M0150",
       definition="承诺交期不早于统计截止日的未发货金额。", rule="与 S05 共同构成订未发结构。")
metric("S08", "超期订未发金额占比", "发货", "复合指标", "比值", "YWLN_M_OVERDUE_PENDING_AMOUNT_SHARE",
       definition="S05 超期订未发金额 ÷ 全部订未发金额。", rule="超过阈值判定超期积压（BR-A04）。")
metric("S09", "计划外发货金额", "发货", "原子指标", "亿元", "YWLN_M0151",
       definition="实际发货数量超过日出货计划部分对应的金额；计划缺失、计划在出货后才修改或行匹配不唯一时按来源问题置空。",
       rule="> 0 判定计划外发货扰动（BR-C05）。")
metric("S10", "发货平均周期", "发货", "原子指标", "天", "YWLN_M0056",
       definition="订单审批至发货的平均天数。", rule="与 S11 比较判定发货周期超标杆（BR-C04）。")
metric("S11", "发货标杆周期", "发货", "原子指标", "天", "YWLN_M0057",
       definition="发货环节标杆天数。", rule="S10 的比较基准。")
metric("S12", "订单超期天数", "发货", "原子指标", "天", "YWLN_M_ORDER_OVERDUE_DAYS",
       prefer=["YWLN_D004", "YWLN_D005", "YWLN_D006", "YWLN_D049", "YWLN_D050"],
       definition="逐单：统计截止日 − 最早承诺发货日；同一订单多行取最早交期，超期天数取最大值。",
       rule="超期订单清单与超期严重度（BR-C03）。", dims="D004、D005、D006、D049、D050")
metric("S13", "发货办理订单电量", "发货", "原子指标", "GWh", "YWLN_M0312", prefer=["YWLN_D024"],
       definition="按发货办理状态（逾期未完成 / 临期未完成 / 正常未完成 / 逾期完成 / 正常完成）统计的订单电量。",
       rule="逾期未完成或逾期完成电量 > 0 判定发货办理逾期（BR-C08）。", dims="D024")
metric("C01", "商机获取金额", "根因判定", "原子指标", "亿元", "YWLN_M0023",
       definition="有效商机月度预测金额汇总（看板商机获取口径）。", rule="已签单商机占比的分母（C10）。")
metric("C02", "商机获取电量", "根因判定", "原子指标", "GWh", "YWLN_M0022",
       definition="有效商机月度预测电量汇总（看板商机获取口径）。", rule="商机覆盖的电量侧证据。")
metric("C03", "商机预测缺口", "根因判定", "复合指标", "亿元", "YWLN_M0140",
       definition="目标销售额 − 商机预测金额。", rule="> 0 判定上游商机覆盖不足（BR-C01），联动商机获取卡片 RK01。")
metric("C04", "已签单商机获取金额", "根因判定", "原子指标", "亿元", "YWLN_M0198",
       definition="已关联有效订单的商机预测金额。", rule="已签单商机占比的分子（C10）。")
metric("C05", "已签单商机获取电量", "根因判定", "原子指标", "GWh", "YWLN_M0194",
       definition="已关联有效订单的商机预测电量。", rule="签单转化的电量侧证据。")
metric("C06", "待突破战略客户数", "根因判定", "原子指标", "家", "YWLN_M0257",
       definition="看板口径的待突破战略客户数。", rule="> 0 为 RC07 证据之一；与商机获取节点 R09 口径不同，见说明。",
       dims="D005")
metric("C07", "客户实际发货电量", "根因判定", "原子指标", "MWh", "YWLN_M_CUSTOMER_ACTUAL_ENERGY",
       prefer=["YWLN_D005"], definition="按客户等级汇总的实际发货电量（MWh）。", rule="客户电量缺口的比较对象。",
       dims="D005")
metric("C08", "客户电量缺口", "根因判定", "复合指标", "MWh", "YWLN_M_CUSTOMER_ENERGY_GAP", prefer=["YWLN_D005"],
       definition="客户目标电量 − 客户实际发货电量（MWh），按客户等级汇总；任一侧缺失保持 NULL。",
       rule="战略 / 重要客户缺口 > 0 判定客户缺口集中（BR-A07）。", dims="D005")
metric("C09", "剩余目标订单覆盖率", "根因判定", "派生指标", "比值",
       definition="金额：S04 ÷ (B01 − B02)；电量：S03 ÷ (B03 − B04)；剩余目标 ≤ 0 时不计算。",
       rule="< 1 判定在手订单不足以覆盖剩余目标（BR-A05）。", derived="S04、B01、B02、S03、B03、B04")
metric("C10", "已签单商机占比", "根因判定", "派生指标", "比值",
       definition="C04 已签单商机获取金额 ÷ C01 商机获取金额。", rule="低于 B05 时间进度判定签单转化滞后（BR-C02）。",
       derived="C04、C01")

# ---------------------------------------------------------------- problems / causes / advice
# This card is problem driven: indicator → problem (metric anomaly or data
# problem) → cause → advice.  It has no risk layer; problems take its place.
ISSUES = OrderedDict()
ISSUE_TYPES = {"metric": "指标异常", "data": "数据问题"}


def params_text(params):
    return "；".join(f"{key}={value}" for key, value in (params or {}).items())


def issue(code, name, kind, desc, indicators, rule, condition, level, objects, causes, source, params=None):
    ISSUES[code] = dict(code=code, name=name, kind=kind, type=ISSUE_TYPES[kind], desc=desc,
                        indicators=indicators, rule=rule, condition=condition, level=level, objects=objects,
                        causes=causes, source=source, params=params or {})


# -- metric anomalies (indicator vs target / threshold)
issue("IS01", "销售额与出货量双双落后时间进度", "metric", "销售额达成率与出货量达成率同时低于年度时间进度",
      ["R01", "R02", "B05"], "BR-A01",
      "R01 < B05 且 R02 < B05（均为 0～1 小数；任一侧缺值不判定）",
      "两项中落后较多者 ≥ 15 个百分点 极高；10～15 高；< 10 中（沿用商机获取节点 BR-A02 落后分档）",
      "产品团队、产品类型、客户", ["RC01", "RC02", "RC03", "RC04", "RC05"], "看板 M0003 / M0008 / M0009 对照",
      dict(lagExtremePoints=15, lagHighPoints=10))
issue("IS02", "全年预计达成缺口", "metric", "按已发生实绩＋后续预测推算，全年销售额或出货量预计不达成",
      ["R05", "R07", "R04", "R06"], "BR-A02",
      "R05 < 1 或 R07 < 1（金额、电量分别判断）",
      f"预计达成率 < 0.9 高；0.9～1 中{PENDING}", "产品团队、产品类型、客户",
      ["RC01", "RC02", "RC07"], "看板 M0004 / M0005 / M0011 / M0012 对照", dict(highBelow=0.9))
issue("IS03", "销售额与出货量量价背离", "metric", "销售额与出货量进度差异明显，金额与电量未同步",
      ["R03", "R01", "R02"], "BR-A03",
      f"|R03| ≥ 10 个百分点{PENDING}", f"|R03| ≥ 20 个百分点 高；10～20 中{PENDING}",
      "产品类型、产品团队", ["RC06", "RC05"], "共同分析新增（销售额 × 出货量交叉）",
      dict(gapPoints=10, highGapPoints=20))
issue("IS04", "超期订未发积压", "metric", "承诺交期已过的订单仍未发货，占订未发比例偏高",
      ["S05", "S06", "S08"], "BR-A04",
      f"S05 > 0 且 S08 ≥ 0.2{PENDING}", f"S08 ≥ 0.5 高；0.2～0.5 中{PENDING}",
      "订单、客户、产品团队", ["RC03", "RC04", "RC08"], "看板 M0143 / M0134 / 超期订未发占比",
      dict(share=0.2, highShare=0.5))
issue("IS05", "在手订单不足以覆盖剩余目标", "metric", "订未发金额 / 电量不足以支撑年度剩余目标",
      ["C09", "S03", "S04", "B01", "B02", "B03", "B04"], "BR-A05",
      "剩余目标 > 0 且 C09 < 1（金额、电量分别判断）", f"C09 < 0.5 高；0.5～1 中{PENDING}",
      "产品团队、产品类型", ["RC01", "RC02"], "共同分析新增（订单储备 × 剩余目标）", dict(highBelow=0.5))
issue("IS06", "订单履约率偏低", "metric", "已签订单截至期末的发货履约不足",
      ["O03"], "BR-A06", f"O03 < 0.8{PENDING}", f"O03 < 0.6 高；0.6～0.8 中{PENDING}",
      "订单、客户", ["RC03", "RC04", "RC08"], "看板 M0037", dict(below=0.8, highBelow=0.6))
issue("IS07", "重点客户电量缺口", "metric", "战略 / 重要大客户的目标电量高于实际发货电量",
      ["C08", "C07"], "BR-A07", "客户等级 1（战略）或 2（重要）的 C08 > 0",
      "战略大客户存在缺口 高；仅重要大客户存在缺口 中", "客户、客户等级", ["RC07", "RC01"],
      "看板客户电量缺口", dict(levels="1,2"))
issue("IS08", "订单取消／变更冲减", "metric", "所选期间存在取消或变更订单，冲减订单与后续出货",
      ["O04", "O01"], "BR-A08", "O04 > 0",
      f"O04 ÷ O01 ≥ 0.05 高；其余 中{PENDING}", "订单、客户、产品类型", ["RC09"], "看板取消 / 变更订单电量",
      dict(highShare=0.05))
# -- data problems (the evidence itself is unusable or inconsistent)
issue("DQ01", "指标取数失败或超时", "data", "调用SQL执行失败、超时或结果被截断，对应指标无法使用",
      ["B01", "B02", "B03", "B04"], "BR-DQ02",
      "任一调用SQL状态为失败、超时或截断（查询目录 status ≠ ok）",
      "核心指标（B01～B04）取数失败 高；其他指标 中", "指标、取数链路", ["RC10"], "运行时查询目录",
      dict(core="B01,B02,B03,B04"))
issue("DQ02", "核心指标结果为空", "data", "取数成功但目标或实绩为空，无法计算达成与缺口",
      ["B01", "B02", "B03", "B04"], "BR-DQ03",
      "B01～B04 任一调用SQL状态为 ok 且结果为 NULL", "高", "目标、实绩", ["RC11"], "BR-DQ01 缺值不补零",
      dict(core="B01,B02,B03,B04"))
issue("DQ03", "达成率与基础指标不一致", "data", "看板达成率与实绩 ÷ 目标的复算结果不一致，口径存疑",
      ["R01", "B01", "B02", "R02", "B03", "B04"], "BR-DQ04",
      f"|R01 − B02 ÷ B01| > 0.01 或 |R02 − B04 ÷ B03| > 0.01{PENDING}", "中", "达成率指标",
      ["RC12"], "共同分析新增（口径复核）", dict(tolerance=0.01))
issue("DQ04", "订未发结构不闭合", "data", "超期与正常订未发金额之和与未发货金额不一致",
      ["S04", "S05", "S07"], "BR-DQ05",
      f"S04 > 0 且 |S05 + S07 − S04| ÷ S04 > 0.05{PENDING}", "中", "订未发指标", ["RC12"],
      "共同分析新增（口径复核）", dict(tolerance=0.05))
issue("DQ05", "计划外发货无法核对", "data", "有已发货金额，但计划外发货因计划缺失或匹配不唯一返回空值",
      ["S09", "S02"], "BR-DQ06", "S02 > 0 且 S09 为 NULL", "中", "日出货计划、发货行", ["RC11"],
      "看板 M0151 空值口径")
issue("DQ06", "客户电量缺口单侧缺失", "data", "客户等级分组有实际发货电量，但目标侧缺失导致缺口为空",
      ["C08", "C07"], "BR-DQ07", "同一客户等级 C07 有值且 C08 为 NULL", "中", "客户等级、客户目标",
      ["RC11"], "看板客户电量缺口空值口径")

CAUSES = OrderedDict()


def cause(code, name, group, stage, indicators, rule, condition, method, ai, output, params=None):
    CAUSES[code] = dict(code=code, name=name, group=group, stage=stage, indicators=indicators, rule=rule,
                        condition=condition, method=method, ai=ai, output=output, params=params or {})


cause("RC01", "上游商机预测覆盖不足", "上游商机", "opportunity", ["C03", "C01", "C02"], "BR-C01",
      "C03 商机预测缺口 > 0", "规则",
      "联动商机获取卡片：引用其 RK01 判定与根因，归纳缺口集中的产品团队 / 客户",
      "是否成立、缺口金额、缺口集中对象、商机获取卡片证据引用")
cause("RC02", "签单转化滞后", "订单签订", "order", ["C10", "C04", "C01", "B05", "O05", "O06"], "BR-C02",
      "C10 已签单商机占比 < B05 年度时间消耗", "规则",
      "对比 O05 与 O06 判断订单接收是否同时超标杆；列出预测金额最大的未签单商机",
      "是否成立、签单占比与时间进度差、未签单重点商机清单")
cause("RC03", "超期订单未发（交付执行卡点）", "交付执行", "shipment", ["S05", "S06", "S12"], "BR-C03",
      "S05 > 0 且 S12 存在超期天数 > 0 的订单", "规则 + AI",
      "AI 读取超期订单对应商机的最新项目进展卡点与下一步（YWLN_D_PROJECT_BLOCKER / NEXT_STEP），归纳客户侧 / 内部原因",
      "超期订单清单（订单号、客户、金额、超期天数）、卡点归类、证据")
cause("RC04", "发货周期超标杆", "交付执行", "shipment", ["S10", "S11"], "BR-C04",
      "S10 > S11（严格大于）", "规则", "按产品团队定位周期最长环节", "是否成立、平均周期与标杆差值")
cause("RC05", "计划外发货扰动", "交付计划", "shipment", ["S09"], "BR-C05",
      "S09 计划外发货金额 > 0", "规则",
      "区分计划缺失、计划后改与超计划发货三类来源，说明对销售额与出货量节奏的影响",
      "是否成立、计划外金额、涉及订单行")
cause("RC06", "产品结构或单价偏离目标", "产品结构", "order", ["R09", "R10", "O01", "O02"], "BR-C06",
      f"|R09 − R10| ÷ R10 ≥ 0.1{PENDING}", "规则 + AI",
      "AI 按产品类型（D003）比较订单电量与金额结构，判断是产品结构变化还是价格变化导致量价背离",
      "是否成立、实际与目标单位电量销售额、偏离方向与主要产品类型", dict(deviation=0.1))
cause("RC07", "重点客户需求不足或待突破", "客户", "opportunity", ["C06", "C08", "C07"], "BR-C07",
      "C06 > 0，或客户等级 1 / 2 的 C08 > 0", "规则 + AI",
      "AI 归纳缺口客户的需求变化、份额与在途商机情况；证据不足时标注待核实",
      "缺口客户清单、缺口电量、待突破客户数", dict(levels="1,2"))
cause("RC08", "发货办理逾期", "交付执行", "shipment", ["S13"], "BR-C08",
      "S13 中“逾期未完成”或“逾期完成”电量 > 0", "规则",
      "按产品团队与客户定位逾期办理订单", "是否成立、逾期电量、涉及订单")
cause("RC09", "客户需求变化（取消／变更）", "客户", "order", ["O04", "O02"], "BR-C09",
      "O04 > 0", "规则 + AI",
      "AI 读取 D016 订单状态分组与订单备注，区分客户取消、数量变更与交期变更",
      "取消 / 变更订单清单、涉及电量与金额、变更类型")
cause("RC10", "取数链路异常", "数据质量", "data", ["B01", "B02", "B03", "B04"], "BR-C10",
      "DQ01 成立的查询中存在连接失败、超时或截断错误码", "规则",
      "按错误码区分连接、权限、超时与行数上限；给出受影响指标清单",
      "失败查询清单（指标、错误码、耗时）")
cause("RC11", "源数据未维护或缺失", "数据质量", "data", ["B01", "B03", "S09", "C08"], "BR-C11",
      "DQ02、DQ05 或 DQ06 成立（结果为空或单侧缺失）", "规则 + AI",
      "AI 定位缺失的源字段（目标、日出货计划、客户目标）与维护部门；证据不足时标注待核实",
      "缺失字段、涉及对象与维护责任方")
cause("RC12", "指标口径不一致", "数据质量", "data", ["R01", "R02", "S04", "S05", "S07"], "BR-C12",
      "DQ03 或 DQ04 成立（复算或结构不闭合）", "规则",
      "列出不一致的指标对、两侧数值与差额，说明可能的口径差异（期间、去重、取消订单处理）",
      "不一致指标对、差额与口径说明")

ADVICE = OrderedDict()


def advice(code, cause_code, title, content, obj, owner, deadline, target, acceptance, tracking, priority):
    ADVICE[code] = dict(code=code, cause=cause_code, title=title, content=content, object=obj, owner=owner,
                        deadline=deadline, target=target, acceptance=acceptance, tracking=tracking,
                        priority=priority)


advice("AC01", "RC01", "联动补足商机预测覆盖",
       "按商机获取卡片 RK01 的缺口对象，逐产品团队补齐商机与月度预测，缺口无法补足的给出目标调整建议",
       "商机预测缺口集中的产品团队与客户", "销售负责人（牵头）＋ 产品团队负责人", "10 个工作日",
       "C03 商机预测缺口下降，缺口率回到 5% 以内", "缺口对象逐一有补足计划或调整结论", ["C03", "R05"], "高")
advice("AC02", "RC02", "加速重点商机签单",
       "对预测金额最大的未签单商机逐条明确签单计划与阻碍，订单接收周期超标杆的同步压缩审批环节",
       "未签单重点商机", "销售负责人 ＋ 商务经理", "15 个工作日",
       "C10 已签单商机占比追平 B05 时间进度", "重点商机均有签单计划与时间点；按周更新", ["C10", "O05"], "高")
advice("AC03", "RC03", "逐单清理超期订未发",
       "对超期订单逐单确认卡点与新交期，能发尽发；无法交付的与客户确认取消或延期并更新订单",
       "S12 超期订单清单", "交付经理（牵头）＋ 销售负责人", "5 个工作日",
       "S05 超期订未发金额下降，S08 回到 20% 以下", "每张超期订单有卡点结论与新交期", ["S05", "S08"], "高")
advice("AC04", "RC04", "压缩发货周期",
       "定位审批至发货最长的环节，设定分环节时限并按周跟踪",
       "发货周期最长的产品团队", "交付经理 ＋ 计划经理", "20 个工作日",
       "S10 发货平均周期不高于 S11 标杆", "环节时限发布且执行一周期", ["S10"], "中")
advice("AC05", "RC05", "规范日出货计划",
       "出货前完成日出货计划录入与月度计划生效，超计划发货需补录计划并说明原因",
       "计划外发货涉及订单行", "计划经理（牵头）＋ 交付经理", "10 个工作日",
       "S09 计划外发货金额下降", "当月新增发货行均有出货前生效的计划", ["S09"], "中")
advice("AC06", "RC06", "复盘产品结构与价格",
       "按产品类型对比实际与目标单位电量销售额，区分结构变化与价格变化，提出结构调整或价格策略建议",
       "偏离最大的产品类型", "产品经理 ＋ 销售运营", "10 个工作日",
       "R03 量价差回到 10 个百分点以内", "形成按产品类型的偏离说明与调整建议", ["R03", "R09"], "中")
advice("AC07", "RC07", "重点客户缺口专项",
       "对存在电量缺口的战略 / 重要大客户逐户确认需求与份额，制定提量计划；待突破战略客户纳入开拓计划",
       "缺口客户与待突破战略客户", "客户经理（牵头）＋ 销售负责人", "15 个工作日",
       "战略 / 重要大客户 C08 缺口下降", "缺口客户逐户有需求结论与提量计划", ["C08", "C06"], "高")
advice("AC08", "RC08", "督办逾期发货办理",
       "对逾期未完成的发货办理订单逐单督办，逾期完成的复盘原因并纳入时限管理",
       "S13 逾期办理订单", "交付经理", "5 个工作日",
       "S13 逾期未完成电量降为 0", "逾期订单逐单有办理结论", ["S13"], "高")
advice("AC09", "RC09", "复盘取消／变更订单",
       "逐单确认取消 / 变更原因与对后续出货的影响，可挽回的制定挽回方案，不可挽回的同步调整预测",
       "取消 / 变更订单", "销售负责人 ＋ 客户经理", "10 个工作日",
       "O04 取消 / 变更电量占比下降", "每张取消 / 变更订单有原因与处置结论", ["O04"], "中")
advice("AC10", "RC03", "超期订单客户沟通与交期重排",
       "对超期 30 天以上订单与客户共同确认新交期并书面留痕，纳入排产优先级",
       "超期 30 天以上订单", "销售负责人 ＋ 计划经理", "10 个工作日",
       "超期 30 天以上订单数下降", "订单均有客户确认的新交期", ["S12", "S05"], "中")
advice("AC11", "RC10", "排查取数链路并重跑",
       "按失败查询的错误码排查数据库连接、权限与查询耗时，修复后重新分析本卡片",
       "失败或超时的调用SQL", "数据平台负责人", "3 个工作日",
       "全部调用SQL 状态为 ok", "重跑后查询目录无失败、超时或截断", ["B01", "B02", "B03", "B04"], "高")
advice("AC12", "RC11", "补录缺失的源数据",
       "按缺失字段通知维护部门补录目标、日出货计划或客户目标，补录后重新分析",
       "结果为空或单侧缺失的指标对应源数据", "业务数据负责人（牵头）＋ 销售运营", "5 个工作日",
       "DQ02、DQ05、DQ06 不再成立", "缺失字段补录完成并有补录记录", ["B01", "B03", "S09", "C08"], "高")
advice("AC13", "RC12", "开展指标口径对账",
       "对复算不一致或结构不闭合的指标对逐项对账，统一期间、去重与取消订单处理口径，更新指标说明",
       "不一致的指标对", "销售运营（牵头）＋ 数据团队", "10 个工作日",
       "DQ03、DQ04 不再成立", "形成口径对账记录并更新指标说明", ["R01", "R02", "S04"], "中")

# ---------------------------------------------------------------- business rules
RULES = OrderedDict()


def brule(code, name, desc, trigger, result, action, category):
    RULES[code] = dict(code=code, name=name, desc=desc, trigger=trigger, result=result, action=action,
                       category=category)


brule("BR-Q01", "销售额实绩口径",
      "发货明细 new_amount_base 汇总 ÷ 10^8（亿元）；按发货单 new_shipping2_date 归期；仅 new_qty > 0 的发货行",
      "B02、R01、R04、R09", "金额为空不补 0；SUM 忽略单个 NULL", "—", "口径规则")
brule("BR-Q02", "出货量实绩口径",
      "已发货数量 × 产品物料单套电量（kWh）÷ 10^6（GWh）；按发货日期归期",
      "B04、R02、R06、R09", "缺产品电量的发货行不计入电量并在明细披露", "—", "口径规则")
brule("BR-Q03", "目标去重口径",
      "销售目标先按 COALESCE(商机 ID, 目标 ID)＋年度按 createdon DESC、new_targetid DESC 取 rn = 1，再展开 12 个月汇总；"
      "金额 ÷ 10^8，电量 new_month*_power 按 kWh ÷ 10^6（同商机获取节点 BR-Q03 / BR-Q11）",
      "B01、B03、R01、R02、R05、R07、R10、C09", "客户、产品、团队仅为汇总维度，不作去重键", "—", "口径规则")
brule("BR-Q04", "有效订单口径",
      "订单按 OA 审批时间归期；有效订单行沿用看板 M0032 口径；订单状态分正常订单 / 订单变更 / 订单取消（D016）",
      "O01～O04、O03", "取消订单在履约率分子分母两侧同时排除", "—", "口径规则")
brule("BR-Q05", "订未发与超期判定",
      "承诺发货日 = 订单产品 requestdeliveryby（同一订单多行取最早）；早于统计截止日仍未发货为超期订未发，否则为正常订未发",
      "S03～S08、S12", "金额字段缺失或来源有歧义时返回空值，不补 0", "—", "口径规则")
brule("BR-Q06", "时间进度口径", "年度时间消耗 = 统计截止日已过天数 ÷ 全年天数",
      "B05、RK01、RC02", "统计截止日为所选期末与观察日较早者", "—", "口径规则")
brule("BR-Q07", "共同分析同期间约束",
      "跨环节（商机 / 订单 / 发货）证据必须同一统计期间、同一默认筛选范围；至少两个环节有证据才输出共同分析",
      "全部风险与根因", "期间不一致的证据不合并；缺失环节在结果中披露", "—", "口径规则")
brule("BR-Q08", "跨环节不混算", "不同业务状态（预测 / 订单 / 发货）只做关联比较，不相加为同一指标",
      "R03、C09、RK03、RK05", "跨环节比较须注明各自口径与观察时间", "—", "口径规则")
brule("BR-DQ01", "缺值不补零", "任一输入缺失时相应指标保持 NULL，不以 0 参与比较；问题规则输入缺失时交由模型判断或标注无法判定",
      "全部指标", "缺值条数在结果明细披露", "—", "数据质量")

for code, r in ISSUES.items():
    brule(r["rule"], f"{r['name']}判定", r["condition"],
          "指标计算完成后检测" if r["kind"] == "metric" else "取数完成后检测", r["level"],
          "登记问题实例（" + r["type"] + "）", "指标异常判定" if r["kind"] == "metric" else "数据问题判定")
for code, c in CAUSES.items():
    brule(c["rule"], f"{c['name']}成立判定", "、".join(c["indicators"]) + " 相关", "问题实例登记后",
          c["condition"], "规则判定写入根因分析结果" if c["method"] == "规则"
          else "规则初筛后调用 AI 根因分析，结果需复核", "根因判定")
brule("BR-D01", "行动建议生成", "根因成立后按行动建议模板生成，AI 补充具体对象、数字与时间（数字须来自指标结果）",
      "根因分析完成", "每个成立根因至少一条建议", "—", "决策规则")
brule("BR-D02", "任务令下发", "行动建议经人工确认责任人与期限后合并为任务令下发",
      "建议确认后", "未确认的建议不下发", "按责任角色合并任务令", "决策规则")
brule("BR-L01", "链路完整性", "每个问题至少一个候选根因；每个根因至少一条建议；每条建议只对应一个根因",
      "本体生成与校验", "链路缺失时生成失败", "—", "治理规则")

# ---------------------------------------------------------------- links
links = []
n = 0
for rcode, r in ISSUES.items():
    for ccode in r["causes"]:
        for acode_, a in ADVICE.items():
            if a["cause"] != ccode:
                continue
            n += 1
            links.append(dict(id=f"L{n:03d}", issue=rcode, cause=ccode, advice=acode_))


def names(codes):
    return "\n".join(f"{x} {M[x]['name']}" for x in codes)


# reverse relations
cause_issues = defaultdict(list)
for rcode, r in ISSUES.items():
    for ccode in r["causes"]:
        cause_issues[ccode].append(rcode)
cause_advice = defaultdict(list)
for acode_, a in ADVICE.items():
    cause_advice[a["cause"]].append(acode_)
metric_issues, metric_causes, metric_advice = defaultdict(set), defaultdict(set), defaultdict(set)
for rcode, r in ISSUES.items():
    for m in r["indicators"]:
        metric_issues[m].add(rcode)
for ccode, c in CAUSES.items():
    for m in c["indicators"]:
        metric_causes[m].add(ccode)
for acode_, a in ADVICE.items():
    for m in a["tracking"]:
        metric_advice[m].add(acode_)

# ---------------------------------------------------------------- SQL per metric
import pglast
from pglast.stream import RawStream

steps = OrderedDict()
for code, spec in M.items():
    if spec["derived"]:
        spec.update(sql="", query_key="", template="", cte=[], status=f"派生：由 {spec['derived']} 计算，无独立 SQL",
                    board_caliber="—", tables=set())
        continue
    q = pick_query(spec["board"], spec["prefer"])
    sql = render_sql(q["sql_text"])
    tree = pglast.parse_sql(sql.split("\n", 2)[2] if sql.startswith("--") else sql)
    stmt = tree[0].stmt
    ctes = []
    with_clause = getattr(stmt, "withClause", None)
    if with_clause is not None:
        for cte in with_clause.ctes:
            text = RawStream()(cte.ctequery)
            ctes.append(cte.ctename)
            key = (cte.ctename, hashlib.sha1(text.encode()).hexdigest())
            st = steps.setdefault(key, dict(name=cte.ctename, text=text, metrics=[], materialized=str(
                getattr(cte, "ctematerialized", "")).endswith("Always")))
            st["metrics"].append(code)
    tables = set(re.findall(r"p_fm_edw_v_ods_crm_[a-z0-9_]+", sql))
    spec.update(sql=sql, query_key=q["query_key"],
                template=fit_cell(q["sql_text"], what="看板SQL模板", key=q["query_key"]),
                cte=ctes, tables=tables,
                status="已实现：看板查询模板渲染（可选筛选去除，期间由 parameters 控制）",
                board_caliber=q["description"] or "—", label=q_label(q, spec["board"]))

# ---------------------------------------------------------------- write workbook
wb = openpyxl.Workbook()
wb.remove(wb.active)
HEAD_FILL = PatternFill("solid", fgColor="DCE6F1")
HEAD_FONT = Font(bold=True)


def write(name, header, rows, widths=None):
    ws = wb.create_sheet(name)
    ws.append(header)
    for r in rows:
        ws.append([("" if v is None else v) for v in r])
    for cell in ws[1]:
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    for i, h in enumerate(header, 1):
        w = (widths or {}).get(h) or min(max(len(str(h)) * 2 + 4, 12), 40)
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


used_fields = set()
for spec in M.values():
    used_fields |= set(re.findall(r"\b([a-z_][a-z0-9_]*)\b", spec.get("sql") or ""))
for r in attr_rows:
    table = next((t for t, le in TABLE_TO_LE.items() if le == r[0]), None)
    in_sql = any(table in spec.get("tables", ()) for spec in M.values()) if table else False
    r[13] = "Y" if (in_sql and str(r[4]) in used_fields) else "N"

metric_header = ["指标编码", "指标名称", "分类或阶段", "所属节点", "指标定义", "业务规则", "指标类型", "统计单位",
                 "结果列", "聚合类型", "时间维度", "适用维度", "来源业务对象", "来源逻辑实体", "来源业务属性",
                 "物理字段或阶段参考", "当前看板对应编码", "当前看板SQL实际口径", "核对说明", "SQL实现状态",
                 "版本变更", "触发问题", "判定根因", "跟踪行动建议", "链路角色", "调用SQL依赖CTE数",
                 "调用SQL依赖CTE", "调用SQL", "看板查询键", "看板SQL模板（原文）"]
LE_BO = {r[2]: r[0] for r in le_rows}
BO_NAME = {r[0]: r[1] for r in bo_rows}
metric_rows = []
for code, s in M.items():
    les = sorted({TABLE_TO_LE[t] for t in s.get("tables", ()) if t in TABLE_TO_LE})
    attrs = []
    for le in les:
        for en, row in ATTR_BY_EN[le].items():
            if en in used_fields and re.search(r"\b" + re.escape(en) + r"\b", s["sql"]):
                attrs.append(f"{row[2]} {row[3]}（{en}）")
    roles = []
    if metric_issues.get(code):
        roles.append("触发")
    if metric_causes.get(code):
        roles.append("判定")
    if metric_advice.get(code):
        roles.append("跟踪")
    agg = "比值" if s["unit"] in {"%", "比值"} else "平均" if s["unit"] == "天" else "派生" if s["derived"] else "求和"
    if s["kind"] == "派生指标":
        les = sorted({le for x in re.split(r"[、,]", s["derived"]) for le in
                      ({TABLE_TO_LE[t] for t in M[x.strip()].get("tables", ()) if t in TABLE_TO_LE})})
    metric_rows.append([
        code, s["name"], s["group"], NODE, s["definition"], s["rule"], s["kind"], s["unit"],
        s["board"] or code, agg, s["time"], s["dims"],
        "、".join(sorted({f"{LE_BO.get(le)} {BO_NAME.get(LE_BO.get(le), '')}" for le in les})),
        "、".join(f"{le} {LE_NAME[le]}" for le in les),
        "\n".join(attrs[:40]) + (f"\n…共 {len(attrs)} 项" if len(attrs) > 40 else ""),
        "、".join(sorted(t.replace("p_fm_edw_v_ods_crm_", "").replace("_esb", "") for t in s.get("tables", ()))),
        (f"{s['board']}（{s.get('label', '')}）" if s["board"] else "—"), s["board_caliber"],
        ("派生指标：输入缺失时结果为 NULL（BR-DQ01）" if s["derived"]
         else "调用SQL由看板模板渲染：去除可选筛选块，期间改为 parameters CTE；结果列沿用看板标识"),
        s["status"], "V1 新建", "、".join(sorted(metric_issues.get(code, ()))),
        "、".join(sorted(metric_causes.get(code, ()))), "、".join(sorted(metric_advice.get(code, ()))),
        "、".join(roles) or "补充", len(s["cte"]), "、".join(s["cte"]), s["sql"], s["query_key"], s["template"],
    ])

step_rows = []
step_name_set = {st["name"] for st in steps.values()}
for i, st in enumerate(steps.values(), 1):
    deps = sorted(n for n in step_name_set if n != st["name"] and re.search(r"\b" + re.escape(n) + r"\b", st["text"]))
    tables = sorted(set(re.findall(r"p_fm_edw_v_ods_crm_[a-z0-9_]+", st["text"])))
    les = [f"{TABLE_TO_LE[t]} {LE_NAME[TABLE_TO_LE[t]]}" for t in tables if t in TABLE_TO_LE]
    fields = sorted(set(re.findall(r"\b[a-z]\.(new_[a-z0-9_]+|[a-z]+id)\b", st["text"])))[:30]
    step_rows.append([i, st["name"], "是" if st["materialized"] else "否", "、".join(deps), "、".join(les),
                      "、".join(fields), "、".join(st["metrics"]), "看板查询模板中的公共步骤", st["text"]])

issue_rows = [[r["code"], r["name"], r["type"], r["desc"], NODE, "、".join(r["indicators"]), r["rule"],
               r["condition"], r["level"], r["objects"], "、".join(r["causes"]), params_text(r["params"]),
               r["source"]] for r in ISSUES.values()]
cause_rows = [[c["code"], c["name"], c["group"], c["stage"], "、".join(cause_issues[c["code"]]),
               "、".join(c["indicators"]), c["rule"], c["condition"], c["method"], c["ai"], c["output"],
               params_text(c["params"]), "、".join(cause_advice[c["code"]]),
               "\n".join(f"{a} {ADVICE[a]['title']}（{ADVICE[a]['owner']}，{ADVICE[a]['deadline']}）"
                         for a in cause_advice[c["code"]])] for c in CAUSES.values()]
advice_rows = [[a["code"], a["cause"], CAUSES[a["cause"]]["name"], a["title"], a["content"], a["object"],
                a["owner"], a["deadline"], a["target"], a["acceptance"], "、".join(a["tracking"]), a["priority"],
                "根因成立后按模板生成，AI 补充具体对象、数字与时间（数字须来自指标结果）",
                "参照商机获取节点 V3 行动建议模板"] for a in ADVICE.values()]
link_rows = []
for l in links:
    r, c, a = ISSUES[l["issue"]], CAUSES[l["cause"]], ADVICE[l["advice"]]
    link_rows.append([l["id"], names(r["indicators"]), r["rule"], r["code"], r["name"], r["type"], r["condition"],
                      c["code"], c["name"], names(c["indicators"]), c["rule"], c["method"], a["code"], a["title"],
                      a["owner"], a["deadline"], a["target"], names(a["tracking"]),
                      f"闭环（跟踪 {'、'.join(a['tracking'])}）", "确认后按责任角色合并为任务令下发"])

related = defaultdict(list)
for code, s in M.items():
    for token in re.findall(r"BR-[A-Z]+\d+", s["rule"]):
        related[token].append(f"指标：{code}")
for r in ISSUES.values():
    related[r["rule"]] += [f"问题（{r['type']}）：{r['code']} {r['name']}", "判定指标：" + "、".join(r["indicators"])]
for c in CAUSES.values():
    related[c["rule"]] += [f"根因：{c['code']} {c['name']}", "判定指标：" + "、".join(c["indicators"])]
related["BR-D01"] += ["根因：RC01—RC12", "行动建议：AC01—AC13", "运行记录：RUN07 行动建议记录、RUN08 建议措施项"]
related["BR-D02"] += ["实体：LE13 任务令", "行动建议：AC01—AC13"]
related["BR-L01"] += ["问题：IS01—IS08、DQ01—DQ06", "根因：RC01—RC12", "行动建议：AC01—AC13"]
rule_rows = [[b["code"], b["name"], b["desc"], b["trigger"], b["result"], b["action"], b["category"],
              "\n".join(dict.fromkeys(related.get(b["code"], [])))] for b in RULES.values()]

dim_header = ["维度编码", "维度名称", "维度定义", "维度分类代码", "维度分类名称", "维度对应逻辑实体编码",
              "维度对应业务属性编码", "维度对应业务属性"]


def dim(code, name, definition, cat, catname, le, en):
    row = ATTR_BY_EN[le].get(en) if le else None
    return [code, name, definition, cat, catname, le or "", row[2] if row else "", f"{en}" if en else ""]


dim_rows = [
    dim("D003", "产品类型", "商机客户需求产品类型：电芯、PACK、其他（看板 YWLN_D003）", "product", "产品维度", "LE01", "new_accproducttype"),
    dim("D004", "产品团队", "商机负责人所属团队（看板 YWLN_D004）", "org", "组织维度", "LE10", "name"),
    dim("D005", "客户等级", "1 战略大客户、2 重要大客户、3 一般客户、4 BG 大客户（看板 YWLN_D005）", "customer", "客户维度", "LE05", "new_accountlevel"),
    dim("D006", "具体客户", "商机归属客户（看板 YWLN_D006）", "customer", "客户维度", "LE01", "parentaccountid"),
    dim("D016", "订单状态", "正常订单、订单变更、订单取消（看板 YWLN_D016）", "order", "订单维度", "LE07", "statecode"),
    dim("D024", "发货办理状态", "逾期未完成、临期未完成、正常未完成、逾期完成、正常完成（看板 YWLN_D024）", "shipment", "发货维度", "", ""),
    dim("D044", "通用统计期间", "年 / 月统计期间；各指标按自身业务时间筛选（看板 YWLN_D044）", "time", "时间维度", "", ""),
    dim("D049", "销售订单编号", "订单主表 ordernumber（看板 YWLN_D049）", "order", "订单维度", "LE07", "ordernumber"),
    dim("D050", "承诺发货日", "订单产品 requestdeliveryby，即客户要求交期（看板 YWLN_D050）", "time", "时间维度", "LE08", "requestdeliveryby"),
    dim("D051", "发货结构", "发货、正常订未发、超期订未发（看板 YWLN_D051）", "shipment", "发货维度", "", ""),
]
dr_rows = [
    ["DR01", "D003", "电芯", 1, "opportunity.new_accproducttype IN ('1','电芯')"],
    ["DR02", "D003", "PACK", 2, "opportunity.new_accproducttype IN ('2','PACK')"],
    ["DR03", "D003", "其他", 3, "其余或为空"],
    ["DR04", "D005", "战略大客户", 1, "account.new_accountlevel = '1'"],
    ["DR05", "D005", "重要大客户", 2, "account.new_accountlevel = '2'"],
    ["DR06", "D005", "一般客户", 3, "account.new_accountlevel = '3'"],
    ["DR07", "D005", "BG 大客户", 4, "account.new_accountlevel = '4'"],
    ["DR08", "D016", "正常订单", 1, "normal_order：未取消、无生效变更"],
    ["DR09", "D016", "订单变更", 2, "order_change：已审批生效的非取消变更"],
    ["DR10", "D016", "订单取消", 3, "order_cancel：系统状态 2 或已审批生效的取消变更"],
    ["DR11", "D024", "逾期未完成", 1, "overdue_uncompleted（沿用看板发货办理时限口径）"],
    ["DR12", "D024", "临期未完成", 2, "imminent_uncompleted"],
    ["DR13", "D024", "正常未完成", 3, "normal_uncompleted"],
    ["DR14", "D024", "逾期完成", 4, "overdue_completed"],
    ["DR15", "D024", "正常完成", 5, "normal_completed"],
    ["DR16", "D051", "发货", 1, "已发货部分"],
    ["DR17", "D051", "正常订未发", 2, "requestdeliveryby ≥ 统计截止日（取 M0150）"],
    ["DR18", "D051", "超期订未发", 3, "requestdeliveryby < 统计截止日（取 M0143）"],
]

pending = [f"{r['code']} {r['name']}：{r['condition']}；分级 {r['level']}" for r in ISSUES.values()
           if PENDING in r["condition"] + r["level"]]
pending += [f"{c['code']} {c['name']}：{c['condition']}" for c in CAUSES.values() if PENDING in c["condition"]]
n_attr_used = sum(1 for r in attr_rows if r[13] == "Y")
n_sql = sum(1 for s in M.values() if s["sql"])
explain = [
    ["范围", f"仅“{NODE}”卡片（穿透式问题分析 · 经营指标分组）。跨商机获取、订单接收、发货三个环节，分析销售额与出货量的共同问题。不含投标、报价。"],
    ["链路", "源数据（ded_public）→ 指标 → 问题（指标异常 BR-A* / 数据问题 BR-DQ*）→ 根因（规则 BR-C* 初筛 + 大模型）→ 行动建议 → 任务令（人工确认下发）。"
           "本卡片为“指标 → 问题”驱动，不设风险层：问题表取代风险表，与商机获取等环节卡片的风险表并列。"],
    ["分层", "业务层：业务对象 BO01、BO02、BO03、BO04、BO06、BO07 及其逻辑实体、属性、映射；知识层：指标、业务规则、问题（指标异常 / 数据问题）、根因、行动建议及链路；运行层：RUN01～RUN08。"],
    ["依据", f"本体结构与通用口径：{REF.name}（sha256 {sha(REF)[:12]}）；业务属性：{DICT.name}（sha256 {sha(DICT)[:12]}）；"
           f"指标与调用SQL：{CSV.name}（sha256 {sha(CSV)[:12]}）；卡片现状：bi_agent/cockpit/combined.py 与 sales-shipment-issues 组件。"],
    ["规模", f"业务对象 {len(bo_rows)}；逻辑实体 {len(le_rows)}（源数据 {len(le_rows) - 1}、任务令 1）；业务属性 {len(attr_rows)}（本卡片使用 {n_attr_used}）；"
           f"实体关系 {len(er_rows)}；维度 {len(dim_rows)}；指标 {len(M)}（含调用SQL {n_sql}、派生 {len(M) - n_sql}）；业务规则 {len(RULES)}；"
           f"问题 {len(ISSUES)}（指标异常 {sum(1 for i in ISSUES.values() if i['kind'] == 'metric')}、数据问题 {sum(1 for i in ISSUES.values() if i['kind'] == 'data')}）；根因 {len(CAUSES)}；行动建议 {len(ADVICE)}；完整链路 {len(links)} 条；SQL 计算步骤 {len(step_rows)}；工作表 18 张。"],
    ["编码", "业务对象、逻辑实体与业务属性沿用商机获取节点编码（新增 LE19、LE20）；指标为本卡片编码（B 基础 / R 风险 / O 订单 / S 发货 / C 根因判定），"
           "“当前看板对应编码”列对应看板指标；问题 IS（指标异常）/ DQ（数据问题）、根因 RC、行动建议 AC、规则 BR 为本卡片独立编号。"
           "问题与根因的“判定参数”列为运行时规则函数读取的阈值（key=value）。"],
    ["链路闭环", "指标（触发）→ 问题 → 根因（判定指标）→ 行动建议（跟踪指标回到指标库）；每个问题至少一个候选根因，每个根因至少一条行动建议，每条行动建议只对应一个根因；根因“关联问题”由问题“候选根因”反向生成。"],
    ["与商机卡片关系", "RC01 上游商机预测覆盖不足直接引用商机获取卡片（销售额口径明细）的 RK01 判定；本卡片不重复商机获取节点的商机级根因，只做销售额 × 出货量 × 订单的交叉判断。"],
    ["调用 SQL 用法", "复制“指标”表“调用SQL”列整段到客户 PG（ded_public）执行；改统计期间只改 parameters 中 start_date / end_exclusive；"
                  "observed_at 为观察时点（看板原 SQL 中的当前时间统一改为引用它），复现历史结果时改为当时的观察时点；"
                  "可选筛选（产品线、产品类型、团队、客户等级、客户）已去除，需要筛选时参照“看板SQL模板（原文）”中的 FILTER 块。"],
    ["与商机卡片差异", "①预计销售额 R04 沿用看板口径（已历月份取实际销售额），商机获取节点 B02 只取预测金额；②待突破战略客户 C06 沿用看板 M0257，"
                   "商机获取节点 R09 为“等级 1 且无任何关联商机”；③目标电量统一 kWh ÷ 10^6。比较两张卡片时以各自口径为准。"],
    ["待确认", "以下阈值本体无专家依据，暂按建议值填写，需业务确认后定稿：\n" + "\n".join(pending)],
    ["数据缺口", "C07 / C08 客户电量单位为 MWh（看板口径），与 GWh 指标比较时需换算；S09 计划外发货在计划缺失或行匹配不唯一时返回空值；"
              "LE19 / LE20 字段空值率字典未统计。"],
    ["版本", "V2（2026-11-14）：改为“指标 → 问题”驱动，风险表替换为问题表（指标异常 IS01～IS08、数据问题 DQ01～DQ06），"
           "新增数据质量根因 RC10～RC12 与建议 AC11～AC13，问题与根因增加机器可读的判定参数。V1 保持不变。"],
]
write("说明", [f"亿纬锂能本体 · {NODE} V2", ""], explain, {f"亿纬锂能本体 · {NODE} V2": 18, "": 120})
write("业务对象", bo_header, bo_rows)
write("对象关系", bor_header, bor_rows)
write("逻辑实体", le_header, le_rows)
write("业务属性", attr_header, attr_rows)
write("实体关系", er_header, er_rows)
write("逻辑实体映射", lem_header, lem_rows)
write("业务属性映射", map_header, map_rows)
write("维度", dim_header, dim_rows)
write("维度派生规则", ["维度派生规则编码", "维度编码", "维度枚举值名称", "序号", "规则表达式"], dr_rows)
write("指标", metric_header, metric_rows, {"指标定义": 40, "业务规则": 40, "调用SQL": 60, "看板SQL模板（原文）": 40,
                                           "来源业务属性": 36, "当前看板SQL实际口径": 40})
write("指标SQL计算步骤", ["序号", "步骤CTE", "物化", "依赖步骤", "读取逻辑实体", "读取源字段", "使用该步骤的指标", "说明",
                        "SQL片段"], step_rows, {"SQL片段": 80})
write("业务规则", ["规则编码", "规则名称", "规则描述", "触发条件", "判断或结果", "处置动作", "规则类别", "关联本体元素"],
      rule_rows, {"规则描述": 50, "判断或结果": 40, "关联本体元素": 36})
write("问题", ["问题编码", "问题名称", "问题类型", "问题描述", "节点", "触发指标", "判定规则", "成立条件", "问题等级规则",
             "影响对象", "候选根因", "判定参数", "来源"], issue_rows, {"成立条件": 40, "问题等级规则": 40})
write("根因", ["根因编码", "根因名称", "根因分组", "所属环节", "关联问题", "判定指标", "根因成立规则", "成立条件", "判定方式",
             "AI 分析要点", "输出", "判定参数", "行动建议编码", "行动建议"], cause_rows,
      {"成立条件": 36, "AI 分析要点": 40, "输出": 30, "行动建议": 36})
write("行动建议", ["行动建议编码", "对应根因", "根因名称", "行动建议", "行动内容", "作用对象", "责任角色", "期限", "目标值",
               "验收标准", "跟踪指标", "优先级", "生成方式", "来源"], advice_rows, {"行动内容": 44, "目标值": 30, "验收标准": 30})
write("指标-问题-根因-行动建议链路", ["链路编号", "触发指标", "判定规则", "问题编码", "问题名称", "问题类型", "问题成立条件", "根因编码",
                              "根因名称", "判定指标", "根因成立规则", "判定方式", "行动建议编码", "行动建议", "责任角色",
                              "期限", "目标值", "跟踪指标", "闭环", "下一步"], link_rows)
write("分析运行记录模型", run_header, run_rows)
wb.save(OUT)

summary = dict(out=str(OUT), metrics=len(M), sql=n_sql, issues=len(ISSUES), causes=len(CAUSES), advice=len(ADVICE),
               links=len(links), rules=len(RULES), steps=len(step_rows), attrs=len(attr_rows), attrs_used=n_attr_used,
               entities=len(le_rows), relations=len(er_rows))
print(json.dumps(summary, ensure_ascii=False))
