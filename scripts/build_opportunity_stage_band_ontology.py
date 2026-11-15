"""Write the 商机获取 ontology version with the stage-cycle overrun bands.

Base:   docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_储能客户口径修订.xlsx
Adds:   阶段周期及超时分档_真实动态均值口径.xlsx → metrics R12–R17 with their SQL,
        risk RK11 (rule BR-A11), causes RC10 / RC11 (rules BR-C10 / BR-C11),
        advice AC13 / AC14, RC08 linked to RK11, chain rows L032–L034.
Output: docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_阶段周期超时分档版.xlsx

    python scripts/build_opportunity_stage_band_ontology.py
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_储能客户口径修订.xlsx"
BANDS = ROOT / "docs/亿纬锂能/阶段周期及超时分档_真实动态均值口径.xlsx"
OUTPUT = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_阶段周期超时分档版.xlsx"
CELL_LIMIT = 32767
CHANGE = "2026-11-14阶段周期超时分档新增"

RISK_NAME = "商机推进阶段周期超均值较多，拖慢签单"
RISK_CONDITION = ("R13、R15、R17 任一商机数 > 0（存在实际周期 ≥ 同期间同阶段同产品真实动态平均周期 × 1.5 的已结束商机）；"
                  "R12、R14、R16 超均值未满 50% 只作关注，不单独成立")
RISK_LEVEL = "超均值 50% 及以上的商机覆盖 ≥ 2 个阶段，或其预测金额合计 ≥ 10 亿元 高；其他 中"
STAGE_CAUSE = {"商机获取": ("RC08", "AC12"), "技术交流": ("RC10", "AC13"), "方案推动": ("RC11", "AC14")}


def clean(value):
    return "" if value is None else str(value).strip()


def header(ws):
    return {clean(cell.value): cell.column for cell in ws[1] if clean(cell.value)}


def find_row(ws, code):
    for row in range(2, ws.max_row + 1):
        if clean(ws.cell(row, 1).value) == code:
            return row
    return None


def last_row(ws):
    row = ws.max_row
    while row > 1 and not any(clean(ws.cell(row, col).value) for col in range(1, ws.max_column + 1)):
        row -= 1
    return row


def append(ws, values, style_row=None):
    """Append one row, styled like ``style_row`` (default: the last row)."""
    cols = header(ws)
    unknown = set(values) - set(cols)
    if unknown:
        raise SystemExit(f"{ws.title} 没有这些列：{sorted(unknown)}")
    if find_row(ws, clean(values[next(iter(cols))] if next(iter(cols)) in values else "")):
        raise SystemExit(f"{ws.title} 已有编码 {values.get(next(iter(cols)))}，不重复追加")
    source = style_row or last_row(ws)
    target = last_row(ws) + 1
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(target, col)
        template = ws.cell(source, col)
        if template.has_style:
            cell._style = copy.copy(template._style)
    if ws.row_dimensions[source].height:
        ws.row_dimensions[target].height = ws.row_dimensions[source].height
    for name, value in values.items():
        text = "" if value is None else value
        if isinstance(text, str) and len(text) > CELL_LIMIT:
            raise SystemExit(f"{ws.title}.{name} 超过 Excel 单元格上限")
        ws.cell(target, cols[name]).value = text
    return target


def set_cell(ws, code, column, value):
    row = find_row(ws, code)
    if row is None:
        raise SystemExit(f"{ws.title} 缺少 {code}")
    ws.cell(row, header(ws)[column]).value = value


def get_cell(ws, code, column):
    row = find_row(ws, code)
    if row is None:
        raise SystemExit(f"{ws.title} 缺少 {code}")
    return clean(ws.cell(row, header(ws)[column]).value)


def add_items(text, items, sep="、"):
    present = [item for item in re.split(r"[、\n]", text) if item.strip()]
    return sep.join(present + [item for item in items if item not in present])


def read_bands():
    book = openpyxl.load_workbook(BANDS, data_only=True)
    ws = book["指标口径"]
    head_row = next(row for row in range(1, 10) if clean(ws.cell(row, 1).value) == "指标编码")
    names = [clean(ws.cell(head_row, col).value) for col in range(1, ws.max_column + 1)]
    metrics = {}
    for row in range(head_row + 1, ws.max_row + 1):
        values = {name: clean(ws.cell(row, col + 1).value) for col, name in enumerate(names) if name}
        if re.fullmatch(r"R1[2-7]", values.get("指标编码", "")):
            metrics[values["指标编码"]] = values
    sql = {clean(row[0]): row[3] for row in book["查询SQL"].iter_rows(min_row=2, values_only=True) if row[0]}
    means = {clean(row[1]): dict(code=clean(row[0]), start=clean(row[2]), end=clean(row[3]))
             for row in book["阶段平均周期"].iter_rows(min_row=2, values_only=True) if row[0]}
    if sorted(metrics) != [f"R{n}" for n in range(12, 18)] or sorted(sql) != sorted(metrics):
        raise SystemExit("阶段周期分档材料应包含 R12–R17 的口径和 SQL")
    for code, text in sql.items():
        if len(re.findall(r"WHERE code='R1\d'", text)) != 1 or f"WHERE code='{code}'" not in text:
            raise SystemExit(f"{code} 的 SQL 缺少唯一的指标筛选")
    return metrics, sql, means


def band_word(scope):
    return "超平均周期达到 50% 及以上" if ">=" in scope else "超平均周期未满 50%"


def main():
    metrics, sql, means = read_bands()
    book = openpyxl.load_workbook(BASE)
    m_ws, r_ws, k_ws = book["指标"], book["业务规则"], book["风险"]
    c_ws, a_ws, l_ws = book["根因"], book["行动建议"], book["指标-风险-根因-行动建议链路"]
    base_metric = find_row(m_ws, "P0-02")

    # ---- metrics R12–R17 ----------------------------------------------------
    names = {}
    for code in sorted(metrics):
        item = metrics[code]
        stage = item["所属阶段"]
        cause, advice = STAGE_CAUSE[stage]
        mean = means.get(stage, {}).get("code", "")
        scope = item["判定范围"]
        names[code] = item["指标名称"]
        ctes = re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s+AS\s+MATERIALIZED", sql[code])
        values = {
            "指标编码": code, "指标名称": item["指标名称"], "分类或阶段": stage, "所属节点": "商机获取",
            "指标定义": (f"{stage}阶段（{item['开始字段']}→{item['结束字段']}）已结束商机中，实际周期"
                         f"{band_word(scope)}的商机数及其预测金额、电量。动态平均周期基线：{item['动态平均周期基线']}"
                         f"单笔超平均比例＝{item['单笔超平均比例']} 归期：{item['统计期间与归期']}"),
            "业务规则": (f"判定范围：{scope}（{band_word(scope)}）。{item['已结束阶段取值']} "
                         f"过滤：{item['过滤条件']} 空值：{item['空值及异常处理']}"),
            "指标类型": "派生指标", "统计单位": "个／亿元／GWh", "结果列": "数量、金额_亿元、电量_GWh",
            "聚合类型": "count／sum",
            "物理字段或阶段参考": f"商机.{item['开始字段']}／{item['结束字段']}；预测金额 new_forecast_amt_rmb／new_whprice",
            "当前看板对应编码": "", "当前看板SQL实际口径": "看板无同名分档查询",
            "核对说明": f"{item['与已有指标的关系']} 计数与去重：{item['计数与去重']} 预测：{item['预测金额及电量']}",
            "SQL实现状态": "查询已实现；默认2025全年，只改parameters；未在客户库执行验证",
            "V3变更": CHANGE, "触发风险": "RK11", "判定根因": cause, "跟踪行动建议": advice,
            "链路角色": "触发指标（RK11）＋判定指标（" + cause + "）",
            "调用SQL依赖CTE数": str(len(ctes)), "调用SQL依赖CTE": "、".join(ctes), "调用SQL": sql[code],
        }
        for column in ("时间维度", "适用维度", "来源业务对象", "来源逻辑实体", "来源业务属性"):
            values[column] = m_ws.cell(base_metric, header(m_ws)[column]).value
        if not mean:
            raise SystemExit(f"{stage} 缺少阶段平均周期指标")
        append(m_ws, values, style_row=base_metric)

    def lines(codes):
        rows = []
        for code in codes:
            name = names.get(code) or get_cell(m_ws, code, "指标名称")
            rows.append(f"{code} {name}")
        return "\n".join(rows)

    # ---- rules ----------------------------------------------------------------
    rule_row = find_row(r_ws, "BR-A10")
    append(r_ws, {
        "规则编码": "BR-A11", "规则名称": RISK_NAME + "判定",
        "规则描述": ("商机获取、技术交流、方案推动阶段已结束商机的实际周期 ≥ 同期间、同阶段、同产品类型真实动态平均周期 × 1.5；"
                     "基线先由全部完整有效已结束样本求均值，再逐笔分档"),
        "触发条件": "指标计算完成后检测",
        "判断或结果": (RISK_CONDITION + "。某阶段动态平均周期为空或为 0 时该阶段不能判为正常，记无法判定；等级：" + RISK_LEVEL),
        "处置动作": "生成指标异常并登记风险实例", "规则类别": "指标异常判定（→ 风险）",
        "关联本体元素": f"风险：RK11 {RISK_NAME}\n判定指标：R12、R13、R14、R15、R16、R17"}, style_row=rule_row)
    cause_rule_row = find_row(r_ws, "BR-C08")
    append(r_ws, {
        "规则编码": "BR-C10", "规则名称": "技术交流环节卡点成立判定",
        "规则描述": "R14、R15、P1-01、P1-03、P1-04、P1-05、P1-06、P1-07 相关", "触发条件": "风险实例登记后",
        "判断或结果": ("技术交流阶段存在超均值 50% 及以上的已结束商机（R15 > 0）时，按小环节自身起止定位：P1-03 客户准入、"
                       "P1-04 是否需立项、P1-05 送样评审、P1-06 报价管理、P1-07 申请报价；单笔周期 > 同组动态均值 × 1.5"),
        "处置动作": "规则初筛后调用 AI 根因分析，结果需复核", "规则类别": "根因成立判定",
        "关联本体元素": "根因：RC10 技术交流环节卡点\n判定指标：R14、R15、P1-01、P1-03、P1-04、P1-05、P1-06、P1-07"},
        style_row=cause_rule_row)
    append(r_ws, {
        "规则编码": "BR-C11", "规则名称": "方案推动环节卡点成立判定",
        "规则描述": "R16、R17、P2-01、P2-03、P2-04、P2-05 相关", "触发条件": "风险实例登记后",
        "判断或结果": ("方案推动阶段存在超均值 50% 及以上的已结束商机（R17 > 0）时，按小环节自身起止定位：P2-03 签署技术协议或规格书、"
                       "P2-04 质保协议、P2-05 申请中信保限额；单笔周期 > 同组动态均值 × 1.5（P2-05 为资信审批 / P2 阶段替代口径）"),
        "处置动作": "规则初筛后调用 AI 根因分析，结果需复核", "规则类别": "根因成立判定",
        "关联本体元素": "根因：RC11 方案推动环节卡点\n判定指标：R16、R17、P2-01、P2-03、P2-04、P2-05"},
        style_row=cause_rule_row)
    set_cell(r_ws, "BR-Q06", "关联本体元素",
             get_cell(r_ws, "BR-Q06", "关联本体元素")
             + "\n阶段周期分档：R12～R17（同阶段同产品已结束样本均值；先平均后分档，≥ 1.5 倍含恰好 1.5 倍，只计已结束）")
    set_cell(r_ws, "BR-C08", "判断或结果",
             get_cell(r_ws, "BR-C08", "判断或结果") + "；由 RK11 进入时以 R13 > 0（商机获取阶段超均值 50% 及以上）为前提")
    set_cell(r_ws, "BR-C08", "关联本体元素",
             get_cell(r_ws, "BR-C08", "关联本体元素").replace("P0-08", "P0-08、R12、R13", 1))

    # ---- risk RK11 ------------------------------------------------------------
    append(k_ws, {
        "风险编码": "RK11", "风险名称": RISK_NAME,
        "风险描述": ("商机获取、技术交流、方案推动三个阶段中，已结束商机的实际周期超过同期间、同阶段、同产品类型真实动态平均周期 50% 及以上；"
                     "超均值未满 50% 的商机列为关注"),
        "节点": "商机获取", "触发指标": "R12、R13、R14、R15、R16、R17", "异常判定规则": "BR-A11",
        "成立条件": RISK_CONDITION, "风险等级规则": RISK_LEVEL, "影响对象": "商机、客户、产品类型、产品团队",
        "候选根因": "RC08、RC10、RC11", "专家来源": "R12～R17 阶段周期超时分档"})

    # ---- causes -----------------------------------------------------------------
    rc08 = find_row(c_ws, "RC08")
    set_cell(c_ws, "RC08", "关联风险", add_items(get_cell(c_ws, "RC08", "关联风险"), ["RK11"]))
    set_cell(c_ws, "RC08", "判定指标", add_items(get_cell(c_ws, "RC08", "判定指标"), ["R12", "R13"]))
    set_cell(c_ws, "RC08", "成立条件",
             get_cell(c_ws, "RC08", "成立条件") + "；由 RK11 进入时以 R13 > 0 为前提，对 R13 清单商机定位卡点环节")
    output = get_cell(c_ws, "RC08", "输出")
    append(c_ws, {
        "根因编码": "RC10", "根因名称": "技术交流环节卡点", "根因分组": "阶段周期", "关联风险": "RK11",
        "判定指标": "R14、R15、P1-01、P1-03、P1-04、P1-05、P1-06、P1-07", "根因成立规则": "BR-C10",
        "成立条件": get_cell(r_ws, "BR-C10", "判断或结果"), "判定方式": "规则 + AI",
        "AI 分析要点": ("AI 依据客户准入、立项评估、送样测试、报价申请等事件时间与项目进展文本，定位 R15 清单商机卡在哪个环节，"
                        "并给出各环节滞留天数分布；缺环节完成事件时只作文本判断"),
        "输出": output, "行动建议编码": "AC13",
        "行动建议": "AC13 技术交流环节卡点清理（技术支持负责人 ＋ 销售负责人，15 个工作日）"}, style_row=rc08)
    append(c_ws, {
        "根因编码": "RC11", "根因名称": "方案推动环节卡点", "根因分组": "阶段周期", "关联风险": "RK11",
        "判定指标": "R16、R17、P2-01、P2-03、P2-04、P2-05", "根因成立规则": "BR-C11",
        "成立条件": get_cell(r_ws, "BR-C11", "判断或结果"), "判定方式": "规则 + AI",
        "AI 分析要点": ("AI 依据技术协议 / 规格书签署、质保协议、中信保限额或资信审批的事件时间与项目进展文本，定位 R17 清单商机的卡点环节，"
                        "并给出滞留天数分布；P2-05 无独立起止事件时仅作文本判断"),
        "输出": output, "行动建议编码": "AC14",
        "行动建议": "AC14 方案推动环节卡点清理（方案负责人 ＋ 商务负责人，15 个工作日）"}, style_row=rc08)

    # ---- advice -----------------------------------------------------------------
    ac12 = find_row(a_ws, "AC12")
    template = get_cell(a_ws, "AC12", "生成方式")
    append(a_ws, {
        "行动建议编码": "AC13", "对应根因": "RC10", "根因名称": "技术交流环节卡点", "行动建议": "技术交流环节卡点清理",
        "行动内容": ("对 R15 清单中技术交流阶段超均值 50% 及以上的商机，按客户准入、立项评估、送样评审、报价逐环节核对卡点，"
                     "指定责任人并补录环节事件；对仍在技术交流阶段、用时已接近均值的同类商机提前预警"),
        "作用对象": "技术交流超期商机（R15 清单）", "责任角色": "技术支持负责人 ＋ 销售负责人", "期限": "15 个工作日",
        "目标值": "R15 商机数及预测量下降；P1-03～P1-07 环节事件可计算",
        "验收标准": "超期环节逐项关闭或给出新的完成时间；环节事件补录完整",
        "跟踪指标": "R15、P1-01、P1-05", "优先级": "中", "生成方式": template, "来源": "阶段周期超时分档（2026-11-14）"},
        style_row=ac12)
    append(a_ws, {
        "行动建议编码": "AC14", "对应根因": "RC11", "根因名称": "方案推动环节卡点", "行动建议": "方案推动环节卡点清理",
        "行动内容": ("对 R17 清单中方案推动阶段超均值 50% 及以上的商机，逐项核对技术协议 / 规格书、质保协议、中信保限额或资信审批的卡点，"
                     "协调方案与商务资源限期关闭，并补录环节事件"),
        "作用对象": "方案推动超期商机（R17 清单）", "责任角色": "方案负责人 ＋ 商务负责人", "期限": "15 个工作日",
        "目标值": "R17 商机数及预测量下降；P2-03～P2-05 环节周期回落到同组均值以内",
        "验收标准": "每条超期商机卡点关闭或给出新的完成时间；环节事件补录完整",
        "跟踪指标": "R17、P2-01、P2-03、P2-04", "优先级": "中", "生成方式": template, "来源": "阶段周期超时分档（2026-11-14）"},
        style_row=ac12)

    # ---- chain rows -------------------------------------------------------------
    trigger = lines([f"R{n}" for n in range(12, 18)])
    chain = [("L032", "RC08", "商机获取环节卡点", ["R12", "R13", "P0-01", "P0-03", "P0-04", "P0-06", "P0-07"], "BR-C08",
              get_cell(c_ws, "RC08", "判定方式"), "AC12"),
             ("L033", "RC10", "技术交流环节卡点", ["R14", "R15", "P1-01", "P1-03", "P1-04", "P1-05", "P1-06", "P1-07"],
              "BR-C10", "规则 + AI", "AC13"),
             ("L034", "RC11", "方案推动环节卡点", ["R16", "R17", "P2-01", "P2-03", "P2-04", "P2-05"], "BR-C11",
              "规则 + AI", "AC14")]
    style = find_row(l_ws, "L031")
    for link, cause, cause_name, indicators, rule, method, advice in chain:
        tracking = [code for code in get_cell(a_ws, advice, "跟踪指标").split("、") if code]
        append(l_ws, {
            "链路编号": link, "触发指标": trigger, "异常判定规则": "BR-A11", "风险编码": "RK11", "风险名称": RISK_NAME,
            "风险成立条件": RISK_CONDITION, "根因编码": cause, "根因名称": cause_name, "判定指标": lines(indicators),
            "根因成立规则": rule, "判定方式": method, "行动建议编码": advice,
            "行动建议": get_cell(a_ws, advice, "行动建议"), "责任角色": get_cell(a_ws, advice, "责任角色"),
            "期限": get_cell(a_ws, advice, "期限"), "目标值": get_cell(a_ws, advice, "目标值"),
            "跟踪指标": lines(tracking), "闭环": f"闭环（跟踪 {'、'.join(tracking)}）",
            "下一步": "确认后按责任角色合并为任务令下发"}, style_row=style)

    # ---- 说明 -------------------------------------------------------------------
    note = book["说明"]
    counts = dict(指标=last_row(m_ws) - 1, 业务规则=last_row(r_ws) - 1, 风险=last_row(k_ws) - 1,
                  根因=last_row(c_ws) - 1, 行动建议=last_row(a_ws) - 1, 链路=last_row(l_ws) - 1)
    for row in range(1, note.max_row + 1):
        key = clean(note.cell(row, 1).value)
        value = clean(note.cell(row, 2).value)
        if key == "版本":
            note.cell(row, 2).value = (
                "2026-11-14阶段周期超时分档版。在储能客户口径修订版基础上，新增R12～R17阶段周期超时分档指标"
                "（商机获取、技术交流、方案推动三阶段；超同阶段同产品真实动态平均周期未满50%／达到50%及以上），"
                f"共同触发新增风险RK11（规则BR-A11），根因RC08（关联扩至RK11）、新增RC10、RC11（规则BR-C10、BR-C11），"
                "行动建议AC12、新增AC13、AC14，链路L032～L034。原有指标、口径与SQL不变。")
        elif key == "规模":
            value = re.sub(r"指标\d+", f"指标{counts['指标']}", value)
            value = re.sub(r"业务规则\d+", f"业务规则{counts['业务规则']}", value)
            value = re.sub(r"风险\d+", f"风险{counts['风险']}", value)
            value = re.sub(r"根因\d+", f"根因{counts['根因']}", value)
            value = re.sub(r"行动建议\d+", f"行动建议{counts['行动建议']}", value)
            value = re.sub(r"完整链路\d+条", f"完整链路{counts['链路']}条", value)
            note.cell(row, 2).value = value
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    book.save(OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)}  " + " ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
