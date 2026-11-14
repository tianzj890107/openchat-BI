"""Build the 销售额／出货量共同问题分析 runtime config from its ontology workbook.

The card is problem driven: indicators → problems (metric anomalies and data
problems) → causes → advice.  Everything the runtime judges with — metric
SQL, problem and cause conditions, their thresholds ("判定参数"), the links
and the advice — is read from the workbook; nothing is written here by hand.

Usage: python scripts/build_sales_shipment_config.py
"""
import hashlib
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_销售额出货量共同问题分析_V2.xlsx"
OUTPUT = ROOT / "bi_agent/cockpit/assets/sales-shipment/config.json"
VERSION = "sales-shipment-rules-1"


def clean(value):
    return "" if value is None else str(value).strip()


def codes(value):
    return [item.strip() for item in re.split(r"[、,，\n]", clean(value)) if item.strip()]


def rows(workbook, sheet):
    data = [r for r in workbook[sheet].iter_rows(values_only=True) if r and any(c not in (None, "") for c in r)]
    header = [clean(c) for c in data[0]]
    return [dict(zip(header, row)) for row in data[1:]]


def parse_params(text):
    """"key=value；key2=value2" → {key: number-or-text}."""
    params = {}
    for part in re.split(r"[；;]", clean(text)):
        if "=" not in part:
            continue
        key, value = (item.strip() for item in part.split("=", 1))
        try:
            params[key] = int(value) if re.fullmatch(r"-?\d+", value) else float(value)
        except ValueError:
            params[key] = value
    return params


def build():
    workbook = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)
    explain = {clean(r[0]): clean(r[1]) for r in workbook["说明"].iter_rows(values_only=True) if r and r[0]}
    title = clean(next(workbook["说明"].iter_rows(values_only=True))[0])

    metrics = {}
    for row in rows(workbook, "指标"):
        code = clean(row["指标编码"])
        board = clean(row["当前看板对应编码"]).split("（", 1)[0]
        metrics[code] = dict(
            code=code, name=clean(row["指标名称"]), group=clean(row["分类或阶段"]), kind=clean(row["指标类型"]),
            unit=clean(row["统计单位"]), definition=clean(row["指标定义"]), rule=clean(row["业务规则"]),
            timeDimension=clean(row["时间维度"]), dimensions=clean(row["适用维度"]),
            resultColumn=board if board and board != "—" else "",
            # Dimensions the query returns as result columns, from its dashboard
            # query key "M|metrics|dimensions|_" (not the optional filters
            # listed under 适用维度, nor aliases inside intermediate steps).
            groupBy=[d.replace("YWLN_", "") for d in clean(row["看板查询键"]).split("|")[2].split(",") if d]
            if clean(row["看板查询键"]).count("|") >= 3 else [],
            sql=clean(row["调用SQL"]), sqlStatus=clean(row["SQL实现状态"]),
            derived=clean(row["指标类型"]) == "派生指标", entities=clean(row["来源逻辑实体"]),
            boardCaliber=clean(row["当前看板SQL实际口径"]),
        )
    issues = {}
    for row in rows(workbook, "问题"):
        code = clean(row["问题编码"])
        issues[code] = dict(
            code=code, name=clean(row["问题名称"]), type=clean(row["问题类型"]),
            kind="data" if clean(row["问题类型"]) == "数据问题" else "metric",
            description=clean(row["问题描述"]), indicators=clean(row["触发指标"]), rule=clean(row["判定规则"]),
            condition=clean(row["成立条件"]), levelRule=clean(row["问题等级规则"]), objects=clean(row["影响对象"]),
            causes=codes(row["候选根因"]), params=parse_params(row["判定参数"]), source=clean(row["来源"]),
        )
    causes = {}
    for row in rows(workbook, "根因"):
        code = clean(row["根因编码"])
        causes[code] = dict(
            code=code, name=clean(row["根因名称"]), group=clean(row["根因分组"]), stage=clean(row["所属环节"]),
            issues=codes(row["关联问题"]), indicators=clean(row["判定指标"]), rule=clean(row["根因成立规则"]),
            condition=clean(row["成立条件"]), method=clean(row["判定方式"]), aiFocus=clean(row["AI 分析要点"]),
            output=clean(row["输出"]), params=parse_params(row["判定参数"]), advice=codes(row["行动建议编码"]),
        )
    advice = {}
    for row in rows(workbook, "行动建议"):
        code = clean(row["行动建议编码"])
        advice[code] = dict(
            code=code, name=clean(row["行动建议"]), action=clean(row["行动建议"]), causes=codes(row["对应根因"]),
            measure=clean(row["行动内容"]), object=clean(row["作用对象"]), owner=clean(row["责任角色"]),
            deadline=clean(row["期限"]), target=clean(row["目标值"]), acceptance=clean(row["验收标准"]),
            tracking=clean(row["跟踪指标"]), priority=clean(row["优先级"]), source=clean(row["来源"]),
        )
    rules = {}
    for row in rows(workbook, "业务规则"):
        code = clean(row["规则编码"])
        rules[code] = dict(code=code, name=clean(row["规则名称"]), description=clean(row["规则描述"]),
                           trigger=clean(row["触发条件"]), result=clean(row["判断或结果"]),
                           action=clean(row["处置动作"]), category=clean(row["规则类别"]))
    links = {}
    for row in rows(workbook, "指标-问题-根因-行动建议链路"):
        issue = clean(row["问题编码"])
        entry = links.setdefault(issue, dict(issue=issue, causes=[], advice=[]))
        for key, value in (("causes", clean(row["根因编码"])), ("advice", clean(row["行动建议编码"]))):
            if value and value not in entry[key]:
                entry[key].append(value)

    # The links table must agree with the problem and cause sheets.
    for code, spec in issues.items():
        if code not in links or set(links[code]["causes"]) != set(spec["causes"]):
            raise SystemExit(f"问题 {code} 的候选根因与链路不一致")
        for metric in codes(spec["indicators"]):
            if metric not in metrics:
                raise SystemExit(f"问题 {code} 引用不存在的指标 {metric}")
        if spec["rule"] not in rules:
            raise SystemExit(f"问题 {code} 引用不存在的规则 {spec['rule']}")
    for code, spec in causes.items():
        if not spec["advice"]:
            raise SystemExit(f"根因 {code} 没有行动建议")
    for code, spec in metrics.items():
        if not spec["derived"] and not (spec["sql"] and spec["resultColumn"]):
            raise SystemExit(f"指标 {code} 缺少调用SQL或结果列")

    return dict(
        version=VERSION, ontology=title.replace("亿纬锂能本体 · ", ""),
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest()),
        notes=dict(caliber=explain.get("与商机卡片差异", ""), pending=explain.get("待确认", ""),
                   dataGaps=explain.get("数据缺口", ""), version=explain.get("版本", "")),
        metrics=metrics, issues=issues, causes=causes, advice=advice, rules=rules, links=links,
    )


def main():
    config = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT).as_posix()}")
    print(f"metrics={len(config['metrics'])} issues={len(config['issues'])} causes={len(config['causes'])} "
          f"advice={len(config['advice'])} rules={len(config['rules'])}")


if __name__ == "__main__":
    main()
