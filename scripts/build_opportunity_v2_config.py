"""Build the reviewed runtime config for the opportunity V2 ontology card.

The customer workbook is an authoring artifact.  The card never reads it at
runtime: this script extracts only the reviewed entities, fields, indicators,
rules and risk/cause/advice links into a versioned JSON config, together with
the source hash for audit.  Re-run it when the V2 workbook changes.

Usage::

    .venv/bin/python scripts/build_opportunity_v2_config.py

The generated file is committed.  The source workbook is not required in the
customer image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V2.xlsx"
DICTIONARY = ROOT / "docs/亿纬锂能/ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx"
OUTPUT = ROOT / "bi_agent/cockpit/assets/opportunity-v2/config.json"


FIELD_NAMES = {
    "LE01": [
        "opportunityid", "name", "parentaccountid", "new_accountlevel",
        "new_accproducttype", "new_processstage", "new_approvalstatus_acneed",
        "new_approvalstatus", "new_opportunitystatus", "new_contractconfirmation",
        "new_contractconfirmation_date", "createdon", "new_stage1enddate",
        "new_stage2enddate", "new_stage3enddate", "new_stage4enddate",
        "new_stage5enddate", "ownerid", "statecode", "estimatedvalue",
        "new_projectpower", "new_forecasttime",
    ],
    "LE02": [
        "new_oppmonthid", "new_opportunity_id", "new_accountdate",
        "new_forecast_amt_rmb", "new_amt_rmb", "new_forcastpower",
        "new_orderforecast_qty", "statecode", "new_approvalstatus",
    ],
    "LE04": [
        "new_projectprocessid", "new_opportunity_id", "new_desc", "new_sdate",
        "new_edate", "new_question_resource", "new_projectstage",
    ],
    "LE05": ["accountid", "name", "new_accountlevel", "createdon", "statecode"],
    "LE06": [
        "new_targetid", "new_year", "new_account_id", "new_producttype_id",
        "new_dept_id", "new_opportunity_id", "new_project_name", "statecode",
        *[f"new_month{i}" for i in range(1, 13)],
        *[f"new_month{i}_quantity" for i in range(1, 13)],
        *[f"new_month{i}_power" for i in range(1, 13)],
    ],
    "LE07": ["salesorderid", "new_contract_num", "new_contract_amt", "statecode", "statuscode"],
    "LE08": ["salesorderdetailid", "salesorderid", "new_opportunity_id", "new_product_type", "quantity"],
    "LE09": [
        "seq_no", "project_name", "input_time", "bid_open_time",
        "winner_announce_time", "is_awarded", "bid_open_result", "bid_amount",
        "energy_mwh", "power_mw", "tenderee_full_name",
    ],
    "LE10": ["teamid", "name"],
    "LE11": ["teamid", "systemuserid"],
    "LE12": ["new_product_typeid", "new_accproducttype", "new_name", "new_product_type_code"],
}


def rows(workbook, sheet):
    values = list(workbook[sheet].iter_rows(values_only=True))
    header = [str(value or "") for value in values[0]]
    for row in values[1:]:
        yield {header[index]: (row[index] if index < len(row) else None)
               for index in range(len(header))}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_fields(workbook):
    entities = {}
    for row in rows(workbook, "逻辑实体映射"):
        code = clean(row.get("逻辑实体编码"))
        if code:
            entities[code] = dict(
                code=code,
                name=clean(row.get("逻辑实体名称")),
                english=clean(row.get("逻辑实体英文名")),
                table=clean(row.get("关联物理表")),
                crm=clean(row.get("CRM实体")),
                status=clean(row.get("状态")),
            )
    available = {}
    for row in rows(workbook, "业务属性映射"):
        entity = clean(row.get("逻辑实体编码"))
        english = clean(row.get("业务属性英文名称"))
        if entity and english:
            available[(entity, english)] = dict(
                entity=entity,
                attribute=clean(row.get("业务属性编码")),
                name=clean(row.get("业务属性名称")),
                english=english,
                table=clean(row.get("来源表名")),
                column=clean(row.get("来源字段")),
                mapping=clean(row.get("映射方式")),
            )
    fields = {}
    missing = []
    for entity, names in FIELD_NAMES.items():
        for name in names:
            item = available.get((entity, name))
            if not item:
                missing.append(f"{entity}:{name}")
                continue
            fields.setdefault(entity, {})[name] = item
    if missing:
        raise SystemExit("V2 本体缺少运行时字段映射：" + "、".join(missing))
    return entities, fields


def build_config(workbook):
    entities, fields = build_fields(workbook)
    metrics = {}
    for row in rows(workbook, "指标"):
        code = clean(row.get("指标编码"))
        if code:
            metrics[code] = dict(
                code=code,
                name=clean(row.get("指标名称")),
                definition=clean(row.get("指标定义")),
                formula=clean(row.get("计算公式")),
                caliber=clean(row.get("统计口径")),
                type=clean(row.get("指标类型")),
                entities=[value.strip() for value in clean(row.get("来源逻辑实体")).split("、") if value.strip()],
                attributes=clean(row.get("来源业务属性")),
                unit=clean(row.get("统计单位")),
                dimension=clean(row.get("时间维度")),
                sqlCodes=clean(row.get("当前 SQL 指标对照")),
            )
    rules = {}
    for row in rows(workbook, "业务规则"):
        code = clean(row.get("规则编码"))
        if code:
            rules[code] = dict(
                code=code,
                name=clean(row.get("规则名称")),
                description=clean(row.get("规则描述")),
                trigger=clean(row.get("触发条件")),
                result=clean(row.get("判断或结果")),
                action=clean(row.get("处置动作")),
                category=clean(row.get("规则类别")),
            )
    risks = {}
    for row in rows(workbook, "风险"):
        code = clean(row.get("风险编码"))
        if code:
            risks[code] = dict(
                code=code,
                name=clean(row.get("风险名称")),
                description=clean(row.get("风险描述")),
                indicators=clean(row.get("触发指标")),
                rule=clean(row.get("异常判定规则")),
                condition=clean(row.get("成立条件")),
                levelRule=clean(row.get("风险等级规则")),
                impact=clean(row.get("影响对象")),
                candidateCauses=[value.strip() for value in clean(row.get("候选根因")).split("、") if value.strip()],
            )
    causes = {}
    for row in rows(workbook, "根因"):
        code = clean(row.get("根因编码"))
        if code:
            causes[code] = dict(
                code=code,
                name=clean(row.get("根因名称")),
                group=clean(row.get("根因分组")),
                indicators=clean(row.get("判定指标")),
                rule=clean(row.get("根因成立规则")),
                condition=clean(row.get("成立条件")),
                risks=[value.strip() for value in clean(row.get("关联风险")).split("、") if value.strip()],
                method=clean(row.get("判定方式")),
                aiFocus=clean(row.get("AI 分析要点")),
                output=clean(row.get("输出")),
            )
    advice = {}
    for row in rows(workbook, "决策建议"):
        code = clean(row.get("建议编码"))
        if code:
            advice[code] = dict(
                code=code,
                name=clean(row.get("建议名称")),
                causes=[value.strip() for value in clean(row.get("对应根因")).split("、") if value.strip()],
                measure=clean(row.get("措施")),
                owner=clean(row.get("责任角色")),
                deadline=clean(row.get("期限")),
                tracking=clean(row.get("跟踪指标")),
                method=clean(row.get("生成方式")),
                source=clean(row.get("来源")),
            )
    links = {}
    for row in rows(workbook, "风险根因建议链路"):
        risk = clean(row.get("风险编码"))
        cause = clean(row.get("根因编码"))
        if not risk or not cause:
            continue
        entry = links.setdefault(risk, dict(risk=risk, causes=[], advice=[]))
        if cause not in entry["causes"]:
            entry["causes"].append(cause)
        for token in clean(row.get("决策建议")).replace("\n", "、").split("、"):
            code = token.strip().split(" ", 1)[0]
            if code.startswith("DS") and code not in entry["advice"]:
                entry["advice"].append(code)
    for risk, entry in links.items():
        entry["advice"].extend(
            code for cause in entry["causes"] for code in advice.get(cause, {}).get("causes", [])
            if code not in entry["advice"]
        )

    # Business decisions locked for this card.  They intentionally override
    # the workbook where the workbook conflicts with the accepted contract.
    overrides = {
        "BR-Q02": {
            "decision": "签单按合同签订判断，订单数不构成签单",
            "field": "new_contractconfirmation",
            "confirmed": ["1"],
            "notConfirmed": ["0"],
            "unknown": "空值或非 0/1",
            "note": "new_contractconfirmation_date 实库 0% 覆盖，不能用于测量日判断。",
        },
        "RK07": {
            "decision": "解除 RK07 与 RC01 的矛盾关联",
            "reason": "RK07 客户无商机，不能同时要求存在该客户的 P0 商机。",
            "causes": [],
            "advice": ["DS03"],
        },
        "customerTier": {"strategic": ["0", "1"], "priority": ["2", "4"], "general": ["3"]},
        "stage": {"11": "P0", "12": "P1", "13": "P2", "14": "P3", "15": "P4"},
        "bidMatch": {
            "strategy": "trimmed exact project name; ambiguous duplicate names never judged not bidding",
            "idRelationAvailable": False,
        },
        "dynamicCycle": {
            "multiplier": 1.5,
            "strict": True,
            "sample": "同年度同产品类型、截至测量日已进入阶段的有效商机；完成记录算至结束时间，在途算至测量日；排除缺进入时间或时间倒置记录。",
        },
        "targetAggregation": {
            "decision": "销售目标按行求和，不按客户/产品去重",
            "reason": "本体 BR-Q03 仅要求商机、客户、订单按 ID 去重；目标表无经验证的业务唯一键，按客户/产品 DISTINCT 会破坏目标规模。",
        },
        "electricitySource": {
            "field": "new_orderforecast_qty",
            "nativeUnit": "kWh",
            "outputUnit": "GWh",
            "reason": "本体登记的 new_forcastpower 实库仅 1 条非空，无法用于指标计算；new_orderforecast_qty 覆盖 99.97%，金额/数量比约 330–530 元/kWh。",
        },
        "measurementDate": "历史期间固定在期末；当前期间使用分析启动日，并写入卡片上下文。",
        "thresholds": {
            "gapRateHigh": 0.10,
            "gapRateMedium": 0.05,
            "signLagExtremePoints": 15,
            "signLagHighPoints": 10,
            "quarterWindows": {"3": 0.50, "4": 0.25},
            "focusTrackingRatio": 0.70,
            "productPendingRatio": 0.20,
            "otherPendingRatio": 0.30,
            "productRiskAmountHigh": 30,
            "productRiskAmountMedium": 10,
        },
    }
    # The resolved link table must already reflect the explicit business
    # overrides; the UI and task drafting never re-interpret the workbook.
    links["RK07"] = {"risk": "RK07", "causes": [], "advice": ["DS03"]}
    config = dict(
        version="opportunity-v2-rules-1",
        ontology="商机获取节点 V2",
        source=dict(path=str(SOURCE.relative_to(ROOT)), sha256=digest(SOURCE)),
        dictionary=dict(path=str(DICTIONARY.relative_to(ROOT)), sha256=digest(DICTIONARY)),
        logicalEntities=entities,
        fields=fields,
        metrics=metrics,
        rules=rules,
        risks=risks,
        causes=causes,
        advice=advice,
        links=links,
        overrides=overrides,
        enums=dict(
            customerLevel={"0": "战略", "1": "战略", "2": "重点", "4": "重点", "3": "一般"},
            productType={"1": "电芯", "2": "PACK"},
            processStage={"11": "P0", "12": "P1", "13": "P2", "14": "P3", "15": "P4"},
            acneed={"1": "未申请", "2": "审核中", "3": "审核通过", "4": "已驳回", "5": "废弃"},
            opportunityStatus={"0": "已开始", "1": "赢单", "2": "丢单", "3": "结案"},
            oppApproval={"1": "制单", "2": "审核中", "3": "已审核", "4": "已驳回"},
            monthApproval={"1": "制单", "2": "审核中", "3": "已审核", "4": "已驳回", "5": "已否决", "6": "已撤回"},
            monthState={"0": "有效", "1": "停用"},
            orderState={"0": "有效", "1": "已提交", "2": "已取消", "3": "已完成", "4": "已开发票"},
        ),
    )
    return config


def main():
    workbook = openpyxl.load_workbook(SOURCE, data_only=True, read_only=True)
    config = build_config(workbook)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    print(f"metrics={len(config['metrics'])} risks={len(config['risks'])} "
          f"causes={len(config['causes'])} advice={len(config['advice'])} links={len(config['links'])}")


if __name__ == "__main__":
    main()
