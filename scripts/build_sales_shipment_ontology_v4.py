"""Sync the 商机 part of the 销售额／出货量共同问题分析 ontology from 亿纬锂能本体文件_1117.

Inputs (read-only):
  - docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V3.xlsx  (the card's ontology)
  - docs/亿纬锂能/亿纬锂能本体文件_1117.xlsx                      (商机获取 ontology, 1117)
Output:
  - docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V4.xlsx

What changes (V4):
  - 商机问题 are 1117's three 商机 risks, judged on 1117's own SQL:
      IS11 商机预测覆盖不足        ← RK01（R01）
      IS12 客户预测不足            ← RK06（R08 风险专用正缺口汇总）
      IS13 商机推进超期，影响签单  ← RK11（R12～R17）
    1117's R01 / R08 / R12～R17 are imported as OR01 / OR08 / OR12～OR17
    (this card already uses R01～R10 for its own metrics) with the 1117 SQL
    unchanged (three bound parameters [期初, 次年初, 观察日]).
  - 1117's causes and advice of those risks come along (RC13～RC20,
    AC14～AC22) with their chains; 1117 metrics they only reference and this
    card does not query are written "1117·<code>".
  - Removed: IS02 全年预计达成缺口, IS07 重点客户电量缺口, IS09 / IS10 (read
    from the 商机获取 card), their metrics C01～C08、C10、R04～R07, data check
    DQ06 and cause RC07 / advice AC07.  RC01 and RC02 (still candidate causes
    of IS01 / IS05) now judge on OR01 and OR13 / OR15 / OR17.
Every other sheet row is kept as is.
"""
import copy
import hashlib
import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V3.xlsx"
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能本体文件_1117.xlsx"
OUT = ROOT / "docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V4.xlsx"
NODE = "销售额／出货量共同问题分析"
SYNC = "同步自亿纬锂能本体文件_1117"

# ---- 1117 → this card's codes -------------------------------------------
METRICS = {"R01": "OR01", "R08": "OR08", **{f"R{n}": f"OR{n}" for n in range(12, 18)}}
RISKS = {"RK01": "IS11", "RK06": "IS12", "RK11": "IS13"}
CAUSES = {"RC01": "RC13", "RC07": "RC14", "RC08": "RC15", "RC09": "RC16", "RC10": "RC17",
          "RC11": "RC18", "RC12": "RC19", "RC13": "RC20"}
ADVICE = {"AC01": "AC14", "AC02": "AC15", "AC03": "AC16", "AC11": "AC17", "AC12": "AC18",
          "AC13": "AC19", "AC14": "AC20", "AC15": "AC21", "AC16": "AC22"}
RULES = {"BR-A01": "BR-A11", "BR-A06": "BR-A12", "BR-A11": "BR-A13",
         "BR-C01": "BR-C13", "BR-C07": "BR-C14", "BR-C08": "BR-C15", "BR-C09": "BR-C16",
         "BR-C10": "BR-C17", "BR-C11": "BR-C18", "BR-C12": "BR-C19", "BR-C13": "BR-C20",
         "BR-Q02": "BR-Q09", "BR-Q06": "BR-Q10", "BR-V09": "BR-Q11"}
CODE_MAP = {**METRICS, **RISKS, **CAUSES, **ADVICE, **RULES}
TOKEN = re.compile(r"(?<![A-Za-z0-9·\-])(BR-[A-Z]+\d{2}|RK\d{2}|RC\d{2}|AC\d{2}|P\d-\d{2}|[BRCS]\d{2})(?![0-9])")
# Problem trigger metrics (codes only: the config builder checks each one).
TRIGGERS = {"IS11": "OR01", "IS12": "OR08", "IS13": "OR13、OR15、OR17、OR12、OR14、OR16"}
PARAMS = {"IS11": "gapRateHigh=0.1；gapRateMedium=0.05", "IS12": "",
          "IS13": "stagesHigh=2；amountHigh=10"}
RESULT_COLUMN = {"OR01": "金额_亿元", "OR08": "数量", **{f"OR{n}": "数量" for n in range(12, 18)}}

REMOVED_ISSUES = {"IS02", "IS07", "IS09", "IS10", "DQ06"}
REMOVED_METRICS = {"C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C10", "R04", "R05", "R06", "R07"}
REMOVED_CAUSES = {"RC07"}
REMOVED_ADVICE = {"AC07"}
REMOVED_RULES = {"BR-A02", "BR-A07", "BR-A09", "BR-A10", "BR-DQ07", "BR-C07"}
SQL_COLUMNS = {"调用SQL", "SQL片段", "调用SQL依赖CTE", "看板SQL模板（原文）"}


def clean(value):
    return "" if value is None else str(value).strip()


def convert(text):
    """1117 wording → this card's codes; codes it does not carry become 1117·X."""
    if not isinstance(text, str):
        return text
    return TOKEN.sub(lambda m: CODE_MAP.get(m.group(1), f"1117·{m.group(1)}"), text)


def split(value):
    return [item.strip() for item in re.split(r"[、,，\n]", clean(value)) if item.strip()]


def table(ws):
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    header = [clean(c) for c in rows[0]]
    data = [dict(zip(header, r)) for r in rows[1:] if r and any(c not in (None, "") for c in r)]
    return header, data


def rewrite(ws, header, data):
    """Replace a sheet's data rows, keeping the header and the first data row's style."""
    style = [copy.copy(cell._style) for cell in ws[2]] if ws.max_row >= 2 else []
    heights = ws.row_dimensions[2].height if ws.max_row >= 2 else None
    ws.delete_rows(2, ws.max_row)
    for index, row in enumerate(data, 2):
        for col, key in enumerate(header, 1):
            cell = ws.cell(row=index, column=col, value=row.get(key))
            if col - 1 < len(style):
                cell._style = copy.copy(style[col - 1])
        if heights:
            ws.row_dimensions[index].height = heights


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    wb = openpyxl.load_workbook(BASE)
    src = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)
    _, s_metrics = table(src["指标"])
    _, s_risks = table(src["风险"])
    _, s_causes = table(src["根因"])
    _, s_advice = table(src["行动建议"])
    _, s_rules = table(src["业务规则"])
    _, s_steps = table(src["指标SQL计算步骤"])
    s_metric = {clean(r["指标编码"]): r for r in s_metrics}
    s_names = {f"1117·{code}": clean(r["指标名称"]) for code, r in s_metric.items()}

    # ---- 问题 --------------------------------------------------------------
    header, issues = table(wb["问题"])
    issues = [r for r in issues if clean(r["问题编码"]) not in REMOVED_ISSUES]
    new_issues = []
    for risk in s_risks:
        code = RISKS.get(clean(risk["风险编码"]))
        if not code:
            continue
        new_issues.append({
            "问题编码": code, "问题名称": clean(risk["风险名称"]), "问题类型": "商机问题",
            "问题描述": convert(clean(risk["风险描述"])), "节点": NODE, "触发指标": TRIGGERS[code],
            "判定规则": RULES[{"IS11": "BR-A01", "IS12": "BR-A06", "IS13": "BR-A11"}[code]],
            "成立条件": convert(clean(risk["成立条件"])), "问题等级规则": convert(clean(risk["风险等级规则"])),
            "影响对象": clean(risk["影响对象"]), "候选根因": "、".join(CAUSES[c] for c in split(risk["候选根因"])),
            "判定参数": PARAMS[code] or None, "来源": f"{SYNC} · {clean(risk['风险编码'])} {clean(risk['风险名称'])}",
        })
    new_issues.sort(key=lambda r: r["问题编码"])
    first_dq = next(i for i, r in enumerate(issues) if clean(r["问题编码"]).startswith("DQ"))
    issues = issues[:first_dq] + new_issues + issues[first_dq:]
    for row in issues:
        if clean(row["问题编码"]) in ("IS01", "IS05"):
            row["候选根因"] = "、".join(c for c in split(row["候选根因"]) if c not in REMOVED_CAUSES)
    rewrite(wb["问题"], header, issues)
    issue_by = {clean(r["问题编码"]): r for r in issues}

    # ---- 根因 --------------------------------------------------------------
    header, causes = table(wb["根因"])
    causes = [r for r in causes if clean(r["根因编码"]) not in REMOVED_CAUSES]
    for row in causes:
        code = clean(row["根因编码"])
        if code == "RC01":
            row.update({"关联问题": "IS01、IS05", "判定指标": "OR01",
                        "成立条件": "OR01 商机预测缺口（金额或电量）> 0（商机获取本体 1117 R01 口径：缺口＝年度目标－（进度＋预测））",
                        "AI 分析要点": "引用商机获取本体 1117 RK01 口径：缺口＝年度目标－（进度＋预测），金额、电量分别判断；归纳缺口集中的产品类型",
                        "输出": "是否成立、金额与电量缺口及缺口率"})
        elif code == "RC02":
            row.update({"关联问题": "IS01、IS05", "判定指标": "OR13、OR15、OR17",
                        "成立条件": "OR13、OR15、OR17 任一已结束严重超期商机数 > 0（商机获取本体 1117 BR-A11 口径，固定基线 1.5 倍）",
                        "AI 分析要点": "商机推进阶段严重超期拖慢签单：引用商机获取、技术交流、方案推动三个阶段的严重超期商机数与跨阶段去重预测金额",
                        "输出": "是否成立、严重超期阶段、商机数与去重预测金额"})
        elif code == "RC11":
            row.update({"关联问题": "DQ02、DQ05", "判定指标": "B01、B03、S09",
                        "成立条件": "DQ02 或 DQ05 成立（结果为空）"})
    for cause in s_causes:
        code = CAUSES[clean(cause["根因编码"])]
        related = [RISKS[r] for r in split(cause["关联风险"]) if r in RISKS]
        causes.append({
            "根因编码": code, "根因名称": clean(cause["根因名称"]), "根因分组": clean(cause["根因分组"]),
            "所属环节": "opportunity", "关联问题": "、".join(related),
            "判定指标": convert(clean(cause["判定指标"])), "根因成立规则": convert(clean(cause["根因成立规则"])),
            "成立条件": convert(clean(cause["成立条件"])), "判定方式": clean(cause["判定方式"]),
            "AI 分析要点": convert(clean(cause["AI 分析要点"])), "输出": convert(clean(cause["输出"])),
            "判定参数": None, "行动建议编码": "、".join(ADVICE[a] for a in split(cause["行动建议编码"])),
            "行动建议": convert(clean(cause["行动建议"])),
        })
    rewrite(wb["根因"], header, causes)
    cause_by = {clean(r["根因编码"]): r for r in causes}

    # ---- 行动建议 -------------------------------------------------------------
    header, advice = table(wb["行动建议"])
    advice = [r for r in advice if clean(r["行动建议编码"]) not in REMOVED_ADVICE]
    for row in advice:
        code = clean(row["行动建议编码"])
        if code == "AC01":
            row.update({"行动内容": "按商机获取本体 1117 RK01 口径（OR01）的缺口对象，逐产品类型补齐商机与月度预测，缺口无法补足的给出目标调整建议",
                        "目标值": "OR01 商机预测缺口下降，缺口率回到 5% 以内", "跟踪指标": "OR01"})
        elif code == "AC02":
            row.update({"行动内容": "对严重超期（超固定基线 50% 及以上）的商机逐条明确推进计划与阻碍，优先处理预测金额大的商机，订单接收周期超标杆的同步压缩审批环节",
                        "目标值": "OR13、OR15、OR17 严重超期商机数下降", "跟踪指标": "OR13、OR15、OR17、O05"})
    for item in s_advice:
        advice.append({key: (convert(clean(value)) if value is not None else None) for key, value in item.items()}
                      | {"行动建议编码": ADVICE[clean(item["行动建议编码"])],
                         "对应根因": CAUSES[clean(item["对应根因"])],
                         "来源": f"{SYNC} · {clean(item['行动建议编码'])}"})
    rewrite(wb["行动建议"], header, advice)
    advice_by = {clean(r["行动建议编码"]): r for r in advice}

    # ---- 业务规则 -------------------------------------------------------------
    header, rules = table(wb["业务规则"])
    rules = [r for r in rules if clean(r["规则编码"]) not in REMOVED_RULES]
    for row in rules:
        code = clean(row["规则编码"])
        if code == "BR-C01":
            row.update({"规则描述": "上游商机预测覆盖不足：引用商机获取本体 1117 R01（OR01）缺口＝年度目标－（进度＋预测）",
                        "触发条件": "IS01 或 IS05 成立后判定", "判断或结果": "OR01 金额或电量缺口 > 0 成立",
                        "关联本体元素": "指标：OR01\n根因：RC01 上游商机预测覆盖不足\n判定指标：OR01"})
        elif code == "BR-C02":
            row.update({"规则描述": "签单转化滞后：商机推进已结束阶段严重超期（商机获取本体 1117 BR-A11，固定基线 1.5 倍）",
                        "触发条件": "IS01 或 IS05 成立后判定", "判断或结果": "OR13、OR15、OR17 任一严重超期商机数 > 0 成立",
                        "关联本体元素": "指标：OR13、OR15、OR17\n根因：RC02 签单转化滞后\n判定指标：OR13、OR15、OR17"})
        elif code == "BR-C11":
            row.update({"关联本体元素": "根因：RC11 源数据未维护或缺失\n判定指标：B01、B03、S09"})
        elif code == "BR-L01":
            row.update({"关联本体元素": "问题：IS01、IS03～IS06、IS08、IS11～IS13；数据校验：DQ01—DQ05\n"
                                       "根因：RC01—RC06、RC08—RC20\n行动建议：AC01—AC06、AC08—AC22"})
        elif code in ("BR-D01", "BR-D02"):
            row["关联本体元素"] = re.sub(r"RC01—RC12", "RC01—RC20", re.sub(r"AC01—AC13", "AC01—AC22", clean(row["关联本体元素"])))
    imported = []
    for rule in s_rules:
        code = RULES.get(clean(rule["规则编码"]))
        if not code:
            continue
        category = {"BR-A": "业务问题判定", "BR-C": "根因判定"}.get(code[:4], "口径规则")
        imported.append({key: (convert(clean(value)) if value is not None else None) for key, value in rule.items()}
                        | {"规则编码": code, "规则类别": category})
    order = {code: i for i, code in enumerate(RULES.values())}
    imported.sort(key=lambda r: order[r["规则编码"]])
    # Keep the sheet grouped: Q rules after Q, A after A, C after C.
    for row in imported:
        prefix = row["规则编码"][:4]
        last = max((i for i, r in enumerate(rules) if clean(r["规则编码"]).startswith(prefix)), default=len(rules) - 1)
        rules.insert(last + 1, row)
    rewrite(wb["业务规则"], header, rules)

    # ---- 指标 ----------------------------------------------------------------
    header, metrics = table(wb["指标"])
    metrics = [r for r in metrics if clean(r["指标编码"]) not in REMOVED_METRICS]
    insert_at = next((i for i, r in enumerate(metrics) if clean(r["指标编码"]).startswith("C")), len(metrics))
    new_metrics = []
    for code_1117, code in METRICS.items():
        m = s_metric[code_1117]
        new_metrics.append({
            "指标编码": code, "指标名称": clean(m["指标名称"]), "分类或阶段": "商机",
            "所属节点": NODE, "指标定义": convert(clean(m["指标定义"])), "业务规则": convert(clean(m["业务规则"])),
            "指标类型": clean(m["指标类型"]), "统计单位": clean(m["统计单位"]), "结果列": clean(m["结果列"]),
            "聚合类型": clean(m["聚合类型"]), "时间维度": clean(m["时间维度"]), "适用维度": clean(m["适用维度"]),
            "来源业务对象": clean(m["来源业务对象"]), "来源逻辑实体": clean(m["来源逻辑实体"]),
            "来源业务属性": clean(m["来源业务属性"]), "物理字段或阶段参考": clean(m["物理字段或阶段参考"]),
            "当前看板对应编码": f"{RESULT_COLUMN[code]}（商机获取本体 1117 调用SQL结果列，非看板指标）",
            "当前看板SQL实际口径": "不适用：沿用商机获取本体 1117 调用SQL",
            "核对说明": f"{SYNC} 指标 {code_1117}；调用SQL原样同步，三个位置参数 [start_date, end_exclusive, observed_at]",
            "SQL实现状态": clean(m["SQL实现状态"]), "版本变更": f"V4 新增（{SYNC} {code_1117}）",
            "调用SQL依赖CTE数": m.get("调用SQL依赖CTE数"), "调用SQL依赖CTE": clean(m["调用SQL依赖CTE"]),
            "调用SQL": clean(m["调用SQL"]), "看板查询键": None, "看板SQL模板（原文）": None,
        })
    metrics = metrics[:insert_at] + new_metrics + metrics[insert_at:]
    # Reverse links from the final problem / cause / advice tables.
    for row in metrics:
        code = clean(row["指标编码"])
        triggers = [c for c, r in issue_by.items() if code in split(r["触发指标"])]
        judged = [c for c, r in cause_by.items() if code in split(r["判定指标"])]
        tracked = [c for c, r in advice_by.items() if code in split(r["跟踪指标"])]
        row["触发问题"] = "、".join(triggers) or None
        row["判定根因"] = "、".join(judged) or None
        row["跟踪行动建议"] = "、".join(tracked) or None
        roles = [name for name, hit in (("触发", triggers), ("判定", judged), ("跟踪", tracked)) if hit]
        row["链路角色"] = "、".join(roles) or "补充"
    rewrite(wb["指标"], header, metrics)
    metric_names = {clean(r["指标编码"]): clean(r["指标名称"]) for r in metrics} | s_names

    # ---- 指标SQL计算步骤 -------------------------------------------------------
    header, steps = table(wb["指标SQL计算步骤"])
    kept = []
    for row in steps:
        users = [c for c in split(row["使用该步骤的指标"]) if c not in REMOVED_METRICS]
        if users:
            row["使用该步骤的指标"] = "、".join(users)
            kept.append(row)
    number = max(int(r["序号"]) for r in kept if isinstance(r["序号"], (int, float)))
    for row in s_steps:
        users = [METRICS[c] for c in split(row["使用该步骤的指标"]) if c in METRICS]
        if not users:
            continue
        number += 1
        kept.append({key: (value if key in SQL_COLUMNS else convert(clean(value)) if value is not None else None)
                     for key, value in row.items() if key in header}
                    | {"序号": number, "使用该步骤的指标": "、".join(users),
                       "说明": f"【商机获取本体 1117】{clean(row.get('说明'))}"})
    rewrite(wb["指标SQL计算步骤"], header, kept)

    # ---- 指标-问题-根因-行动建议链路 ----------------------------------------------
    header, _ = table(wb["指标-问题-根因-行动建议链路"])

    def named(codes):
        return "\n".join(f"{c} {metric_names.get(c, '')}".strip() for c in codes)

    chain = []
    for code, issue in issue_by.items():
        for cause_code in split(issue["候选根因"]):
            cause = cause_by[cause_code]
            for advice_code in split(cause["行动建议编码"]):
                item = advice_by[advice_code]
                tracking = split(item["跟踪指标"])
                chain.append({
                    "链路编号": f"L{len(chain) + 1:03d}", "触发指标": named(split(issue["触发指标"])),
                    "判定规则": clean(issue["判定规则"]), "问题编码": code, "问题名称": clean(issue["问题名称"]),
                    "问题类型": clean(issue["问题类型"]), "问题成立条件": clean(issue["成立条件"]),
                    "根因编码": cause_code, "根因名称": clean(cause["根因名称"]),
                    "判定指标": named(split(cause["判定指标"])), "根因成立规则": clean(cause["根因成立规则"]),
                    "判定方式": clean(cause["判定方式"]), "行动建议编码": advice_code,
                    "行动建议": clean(item["行动建议"]), "责任角色": clean(item["责任角色"]),
                    "期限": clean(item["期限"]), "目标值": clean(item["目标值"]),
                    "跟踪指标": named(tracking), "闭环": f"闭环（跟踪 {'、'.join(tracking)}）",
                    "下一步": "确认后按责任角色合并为任务令下发",
                })
    rewrite(wb["指标-问题-根因-行动建议链路"], header, chain)

    # ---- 说明 ----------------------------------------------------------------
    ws = wb["说明"]
    title = ws.cell(row=1, column=1)
    title.value = "亿纬锂能本体 · 销售额／出货量共同问题分析 V4"
    business = [r for r in issue_by.values() if not clean(r["问题编码"]).startswith("DQ")]
    by_type = {}
    for r in business:
        by_type.setdefault(clean(r["问题类型"]), []).append(f"{clean(r['问题编码'])} {clean(r['问题名称'])}")
    sql_count = sum(1 for r in metrics if clean(r["调用SQL"]))
    text = {
        "问题分类": "按销售额口径“商机 → 订单 → 订未发”三个环节分类，卡片固定显示商机、订单、发货三行，各一句话（商机获取本体 1117 BR-V01）：\n"
                    + "\n".join(f"{name}：{'、'.join(by_type.get(name, []))}" for name in ("商机问题", "订单问题", "订未发问题")),
        "依据": f"本体结构与通用口径：亿纬锂能_本体_商机获取节点_V3_无投标_周期红字同步版.xlsx（sha256 395cb8639e0c）；"
                f"商机部分（V4）：亿纬锂能本体文件_1117.xlsx（sha256 {sha(SOURCE)[:12]}）；"
                "业务属性：ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx（sha256 d948b6bf9d06）；"
                "订单与发货指标调用SQL：bp_local_analysis_query_202611141015.csv（sha256 6b7c19557d9b）。",
        "规模": f"指标 {len(metrics)}（含调用SQL {sql_count}、派生 {len(metrics) - sql_count}）；业务规则 {len(rules)}；"
                f"问题 {len(business)}（" + "、".join(f"{k} {len(v)}" for k, v in by_type.items()) + "）、"
                f"数据校验 {len(issue_by) - len(business)}；根因 {len(causes)}；行动建议 {len(advice)}；完整链路 {len(chain)} 条；"
                f"SQL 计算步骤 {len(kept)}。业务对象、逻辑实体、业务属性与维度未变。",
        "编码": "业务对象、逻辑实体与业务属性沿用商机获取节点编码（新增 LE19、LE20）；指标为本卡片编码（B 基础 / R 风险 / O 订单 / S 发货 / C 根因判定 / "
                "OR 商机，OR01、OR08、OR12～OR17 对应商机获取本体 1117 的 R01、R08、R12～R17）；1117 中本卡片不取数的指标写作“1117·编码”。"
                "问题 IS（商机 / 订单 / 订未发问题）、数据校验 DQ、根因 RC、行动建议 AC、规则 BR 为本卡片独立编号。编码仅用于本体与追溯，卡片文字不显示编码。"
                "问题与根因的“判定参数”列为运行时规则函数读取的阈值（key=value）。",
        "与商机卡片关系": "V4 起商机问题直接同步商机获取本体 1117 的三个商机风险，并在本卡片内用 1117 的调用SQL取数判定，不再读取商机获取卡片的发布结果："
                          "IS11 商机预测覆盖不足（1117 RK01，OR01）、IS12 客户预测不足（1117 RK06，OR08 风险专用正缺口汇总）、"
                          "IS13 商机推进超期，影响签单（1117 RK11，OR12～OR17，只以严重超期 OR13、OR15、OR17 成立，金额为跨阶段按商机去重的叠加值）。"
                          "判定条件、等级与描述口径与商机获取卡片一致；对应根因与行动建议（RC13～RC20、AC14～AC22）同步自 1117，"
                          "本卡片只发布问题，不运行根因与建议。",
        "与商机卡片差异": "①商机问题与商机获取卡片同一 1117 口径、同一调用SQL；②目标电量统一 kWh ÷ 10^6；③本卡片订单与发货指标仍按看板口径。",
        "待确认": "\n".join(line for line in clean(next((r[1].value for r in ws.iter_rows() if clean(r[0].value) == "待确认"), "")).split("\n")
                            if not line.startswith("IS02")),
        "数据缺口": "S09 计划外发货在计划缺失或行匹配不唯一时返回空值；LE19 / LE20 字段空值率字典未统计；"
                    "商机部分（OR*）的输入缺失与部分合计以 1117 调用SQL明细为准。",
    }
    for row in ws.iter_rows(min_row=2):
        key = clean(row[0].value)
        if key in text:
            row[1].value = text[key]
        elif key == "版本":
            row[1].value = clean(row[1].value) + (
                "\nV4（2026-11-17）：商机部分同步亿纬锂能本体文件_1117——商机问题改为 IS11 商机预测覆盖不足、IS12 客户预测不足、"
                "IS13 商机推进超期，影响签单，用 1117 的 R01 / R08 / R12～R17 调用SQL（OR01、OR08、OR12～OR17）在本卡片内判定；"
                "同步 1117 根因 RC13～RC20 与行动建议 AC14～AC22；删除 IS02、IS07、IS09、IS10、DQ06、RC07、AC07 及指标 C01～C08、C10、R04～R07；"
                "RC01、RC02 改按 OR01、OR13 / OR15 / OR17 判定。V3 保持不变。")
    wb.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}: metrics={len(metrics)} issues={len(issue_by)} "
          f"causes={len(causes)} advice={len(advice)} rules={len(rules)} chain={len(chain)} steps={len(kept)}")


if __name__ == "__main__":
    main()
