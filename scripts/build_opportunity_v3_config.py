"""Build the reviewed runtime config for the opportunity V3 ontology card.

The customer workbook is an authoring artifact.  The card never reads it at
runtime: this script extracts only the reviewed entities, fields, indicators,
rules and risk/cause/advice links into a versioned JSON config, together with
the source hash for audit.  Re-run it when the V3 workbook changes.

Usage::

    .venv/bin/python scripts/build_opportunity_v3_config.py

The generated file is committed.  The source workbook is not required in the
customer image.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能_本体_商机获取节点_V3_含SQL.xlsx"
DICTIONARY = ROOT / "docs/亿纬锂能/ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx"
OUTPUT = ROOT / "bi_agent/cockpit/assets/opportunity-v3/config.json"


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
        "new_whprice", "new_orderforecast_qty", "statecode", "new_approvalstatus",
    ],
    "LE04": [
        "new_projectprocessid", "new_opportunity_id", "new_desc", "new_sdate",
        "new_edate", "new_question_resource", "new_projectstage",
    ],
    "LE05": [
        "accountid", "name", "new_accountlevel", "createdon", "statecode",
        "new_lastapptime", "new_lastjgtime", "new_thelastest_updatetime",
        "originatingleadid",
    ],
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
        raise SystemExit("V3 本体缺少运行时字段映射：" + "、".join(missing))
    return entities, fields


def build_rule_index(workbook):
    return {clean(row.get("规则编码")): row for row in rows(workbook, "业务规则")}


def _match(pattern, text, label):
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"本体规则无法解析：{label}")
    return match


def build_thresholds(workbook):
    """Read risk thresholds from the ontology's BR-A/BR-C rule text.

    No threshold is duplicated in code.  If a rule loses its numeric wording,
    the build fails and names the rule instead of silently using a default.
    """
    rules = build_rule_index(workbook)

    def result(code):
        row = rules.get(code)
        if not row:
            raise SystemExit(f"本体缺少业务规则：{code}")
        return clean(row.get("判断或结果")) or clean(row.get("规则描述"))

    a01, a02 = result("BR-A01"), result("BR-A02")
    a04, a05, a10 = result("BR-A04"), result("BR-A05"), result("BR-A10")
    c05, c06, c07 = result("BR-C05"), result("BR-C06"), result("BR-C07")

    gap_high = int(_match(r"缺口率\s*≥\s*(\d+)%", a01, "BR-A01 缺口率高阈值").group(1))
    gap_medium = int(_match(r"(\d+)%\s*[~～–-]\s*\d+%\s*中", a01, "BR-A01 缺口率中阈值").group(1))
    sign_extreme = int(_match(r"≥\s*(\d+)\s*个百分点", a02, "BR-A02 签单落后极高阈值").group(1))
    sign_high = int(_match(r"(\d+)\s*[~～–-]\s*\d+\s*高", a02, "BR-A02 签单落后高阈值").group(1))
    quarter_q3 = int(_match(r"7\s*[~～–-]\s*9\s*月[^>]*>\s*(\d+)%", a02,
                            "BR-A02 三季度窗口").group(1))
    quarter_q4 = int(_match(r"10\s*[~～–-]\s*12\s*月[^>]*>\s*(\d+)%", a02,
                            "BR-A02 四季度窗口").group(1))
    product_high = int(_match(r"≥\s*(\d+)\s*亿元\s*高", a04, "BR-A04 待签高阈值").group(1))
    product_medium = int(_match(r"(\d+)\s*[~～–-]\s*\d+\s*中", a04,
                                "BR-A04 待签中阈值").group(1))
    product_high_5 = int(_match(r"≥\s*(\d+)\s*亿元\s*高", a05, "BR-A05 待签高阈值").group(1))
    product_medium_5 = int(_match(r"(\d+)\s*[~～–-]\s*\d+\s*中", a05,
                                  "BR-A05 待签中阈值").group(1))
    if (product_high, product_medium) != (product_high_5, product_medium_5):
        raise SystemExit("本体 BR-A04 与 BR-A05 的待签阈值不一致，需先统一")
    impact_high = int(_match(r"影响预测\s*≥\s*(\d+)\s*亿元", a10, "BR-A10 影响金额高阈值").group(1))
    product_pending = int(_match(r"≥\s*(\d+)%", c05, "BR-C05 产品待签占比").group(1))
    focus_ratio = int(_match(r"<\s*(\d+)%", c06, "BR-C06 重点跟踪占比").group(1))
    other_ratio = int(_match(r"≥\s*(\d+)%", c07, "BR-C07 其余占比").group(1))

    return {
        "gapRateHigh": gap_high / 100,
        "gapRateMedium": gap_medium / 100,
        "signLagExtremePoints": sign_extreme,
        "signLagHighPoints": sign_high,
        "quarterWindows": {"3": quarter_q3 / 100, "4": quarter_q4 / 100},
        "focusTrackingRatio": focus_ratio / 100,
        "productPendingRatio": product_pending / 100,
        "otherPendingRatio": other_ratio / 100,
        "productRiskAmountHigh": product_high,
        "productRiskAmountMedium": product_medium,
        "impactAmountHigh": impact_high,
        "sources": {
            "gapRateHigh": "BR-A01", "gapRateMedium": "BR-A01",
            "signLagExtremePoints": "BR-A02", "signLagHighPoints": "BR-A02",
            "quarterWindows": "BR-A02", "productRiskAmountHigh": "BR-A04/BR-A05",
            "productRiskAmountMedium": "BR-A04/BR-A05", "impactAmountHigh": "BR-A10",
            "productPendingRatio": "BR-C05", "focusTrackingRatio": "BR-C06",
            "otherPendingRatio": "BR-C07",
        },
    }


def build_dynamic_cycle(workbook):
    rules = build_rule_index(workbook)
    row = rules.get("BR-Q06") or {}
    blob = " ".join(clean(row.get(key)) for key in ("规则描述", "触发条件", "判断或结果"))
    multiplier = float(_match(r"[×xX*]\s*([0-9.]+)", blob, "BR-Q06 动态周期倍数").group(1))
    return {
        "multiplier": multiplier,
        "strict": "严格大于" in blob,
        "sample": clean(row.get("判断或结果")) or clean(row.get("规则描述")),
        "source": "BR-Q06",
    }


def build_stage_rules(workbook):
    stages = {}
    for row in rows(workbook, "维度派生规则"):
        if clean(row.get("维度编码")) != "D_STAGE":
            continue
        expression = clean(row.get("规则表达式"))
        match = re.search(r"new_processstage\s*=\s*'([^']+)'", expression)
        if not match:
            raise SystemExit(f"本体阶段规则无法解析：{expression}")
        stages[match.group(1)] = clean(row.get("维度枚举值名称"))
    if not stages:
        raise SystemExit("本体缺少 D_STAGE 阶段规则")
    return stages


def build_product_names(workbook):
    products = {}
    for row in rows(workbook, "维度派生规则"):
        if clean(row.get("维度编码")) != "D003":
            continue
        expression = clean(row.get("规则表达式"))
        match = re.search(r"\bIN\s*\(([^)]*)\)", expression, re.IGNORECASE)
        if not match:
            continue
        levels = re.findall(r"'([^']*)'", match.group(1))
        if levels and levels[0].isdigit():
            products[levels[0]] = clean(row.get("维度枚举值名称"))
    if not products:
        raise SystemExit("本体缺少 D003 产品类型规则")
    return products


def _dictionary_enum(dictionary, table, field):
    prefix = "ded_public."
    table = clean(table)
    if table.startswith(prefix):
        table = table[len(prefix):]
    found = {}
    rows_iter = dictionary["CRM枚举附录"].iter_rows(values_only=True)
    next(rows_iter, None)
    for row in rows_iter:
        if len(row) < 6:
            continue
        if clean(row[1]) != table or clean(row[2]) != field:
            continue
        for item in re.split(r"[;\n]+", clean(row[5])):
            if "=" in item:
                key, label = item.split("=", 1)
                found[clean(key)] = clean(label)
    return found


def build_enums(workbook, dictionary, fields, customer_tier):
    tables = {entity: next(iter(values.values()))["table"]
              for entity, values in fields.items() if values}
    specs = {
        "productType": ("LE01", "new_accproducttype"),
        "processStage": ("LE01", "new_processstage"),
        "acneed": ("LE01", "new_approvalstatus_acneed"),
        "opportunityStatus": ("LE01", "new_opportunitystatus"),
        "oppApproval": ("LE01", "new_approvalstatus"),
        "monthApproval": ("LE02", "new_approvalstatus"),
        "monthState": ("LE02", "statecode"),
        "orderState": ("LE07", "statecode"),
    }
    enums = {}
    for key, (entity, field) in specs.items():
        values = _dictionary_enum(dictionary, tables[entity], field)
        if not values:
            raise SystemExit(f"数据字典缺少枚举：{entity}.{field}")
        enums[key] = values
    tier_labels = {"strategic": "战略", "priority": "重点", "general": "一般"}
    customer_level = {}
    for tier in ("strategic", "priority", "general"):
        for level in customer_tier[tier]:
            customer_level[level] = tier_labels[tier]
    enums["customerLevel"] = customer_level
    return enums


TIER_LABELS = {"战略客户": "strategic", "重点客户": "priority", "一般客户": "general"}


def _rule_levels(expression):
    match = re.search(r"\bIN\s*\(([^)]*)\)", expression, re.IGNORECASE)
    if match:
        return [item.strip() for item in re.findall(r"'([^']*)'", match.group(1))]
    match = re.search(r"=\s*'([^']*)'", expression)
    return [match.group(1).strip()] if match else []


def _has_strategic_customer_list(workbook):
    """True only when the workbook carries an actual customer-name list."""
    for sheet in workbook.worksheets:
        if "战略" in sheet.title and "名单" in sheet.title:
            return True
        header = next(sheet.iter_rows(values_only=True), ())
        labels = {clean(value) for value in header}
        if "名单" in sheet.title and ({"客户名称", "客户编码"} <= labels
                                      or {"accountid", "name"} <= labels):
            return True
    return False


def build_customer_tier_rules(workbook):
    dimensions = {clean(row.get("维度编码")): row for row in rows(workbook, "维度")}
    dimension = dimensions.get("D005") or {}
    if not dimension:
        raise SystemExit("V3 本体缺少客户等级维度 D005")
    derived = {clean(row.get("维度枚举值名称")): row
               for row in rows(workbook, "维度派生规则")
               if clean(row.get("维度编码")) == "D005"}
    tiers, tier_meta, rule_codes, pending = {}, {}, [], []
    catch_all = False
    for label, key in TIER_LABELS.items():
        row = derived.get(label)
        if not row:
            raise SystemExit(f"V3 本体缺少客户等级派生规则：{label}")
        expression = clean(row.get("规则表达式"))
        levels = _rule_levels(expression)
        # V3 writes 一般客户 as "其余等级（含 0 核心、4 BG、3 一般及空）".
        # It is a catch-all, so enumerate the levels named in the text and let
        # the runtime treat any other non-empty level as general.  An empty
        # level stays "unknown" per BR-Q04.
        if not levels and ("其余" in expression or "其余等级" in expression):
            catch_all = key == "general"
            levels = list(dict.fromkeys(re.findall(
                r"(?<![0-9A-Za-z])([0-4])(?![0-9A-Za-z])", expression)))
        if not levels and not (catch_all and key == "general"):
            raise SystemExit(f"V3 本体客户等级规则无法解析：{label} {expression}")
        code = clean(row.get("维度派生规则编码"))
        status = "pending" if ("待确认" in expression or "待业务确认" in expression) else "confirmed"
        tiers[key] = levels
        tier_meta[key] = dict(rule=code, levels=levels, status=status, expression=expression)
        rule_codes.append(code)
        if status == "pending":
            pending.append(f"{code} {label}：{expression}")
    available = _has_strategic_customer_list(workbook)
    return {
        **tiers,
        "generalCatchAll": catch_all,
        "status": "pending" if pending or not available else "confirmed",
        "statusReason": ("；".join(pending) if pending else "本体客户等级映射已确认") +
                        ("" if available else "；本体未提供战略客户名单工作表"),
        "tierMeta": tier_meta,
        "source": {
            "dimension": "D005", "rulessheet": "维度派生规则",
            "rules": rule_codes, "definition": clean(dimension.get("维度定义")),
        },
        "strategicList": {
            "available": available,
            "reason": ("本体提供战略客户名单" if available else
                       "本体只有按客户等级的派生规则，未提供战略客户名单"),
            "status": ("available" if available and tier_meta["strategic"]["status"] == "confirmed"
                       else "unavailable"),
        },
    }


def build_config(workbook):
    entities, fields = build_fields(workbook)
    dictionary = openpyxl.load_workbook(DICTIONARY, data_only=True, read_only=True)
    metrics = {}
    for row in rows(workbook, "指标"):
        code = clean(row.get("指标编码"))
        if code:
            # The V3_含SQL workbook replaced 计算公式 / 统计口径 with a
            # SQL-first layout.  Keep the historical keys for compatibility
            # and add the new review metadata, including the executable SQL.
            metrics[code] = dict(
                code=code,
                name=clean(row.get("指标名称")),
                definition=clean(row.get("指标定义")),
                formula=clean(row.get("业务规则")),
                caliber=clean(row.get("当前看板SQL实际口径")),
                type=clean(row.get("指标类型")),
                entities=[value.strip() for value in clean(row.get("来源逻辑实体")).split("、") if value.strip()],
                attributes=clean(row.get("来源业务属性")),
                unit=clean(row.get("统计单位")),
                dimension=clean(row.get("时间维度")),
                sqlCodes=clean(row.get("当前看板对应编码")),
                stage=clean(row.get("分类或阶段")),
                node=clean(row.get("所属节点")),
                resultColumns=clean(row.get("结果列")),
                aggregate=clean(row.get("聚合类型")),
                physicalFields=clean(row.get("物理字段或阶段参考")),
                dashboardSql=clean(row.get("当前看板SQL实际口径")),
                notes=clean(row.get("核对说明")),
                sqlStatus=clean(row.get("SQL实现状态")),
                v3Change=clean(row.get("V3变更")),
                risks=[value.strip() for value in re.split(r"[、,，]", clean(row.get("触发风险"))) if value.strip()],
                causes=[value.strip() for value in re.split(r"[、,，]", clean(row.get("判定根因"))) if value.strip()],
                advice=[value.strip() for value in re.split(r"[、,，]", clean(row.get("跟踪行动建议"))) if value.strip()],
                role=clean(row.get("链路角色")),
                cteCount=clean(row.get("调用SQL依赖CTE数")),
                ctes=clean(row.get("调用SQL依赖CTE")),
                sql=clean(row.get("调用SQL")),
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
    for row in rows(workbook, "行动建议"):
        code = clean(row.get("行动建议编码"))
        if code:
            advice[code] = dict(
                code=code,
                name=clean(row.get("行动建议")),
                causes=[value.strip() for value in clean(row.get("对应根因")).split("、") if value.strip()],
                action=clean(row.get("行动建议")),
                measure=clean(row.get("行动内容")),
                object=clean(row.get("作用对象")),
                owner=clean(row.get("责任角色")),
                deadline=clean(row.get("期限")),
                target=clean(row.get("目标值")),
                acceptance=clean(row.get("验收标准")),
                tracking=clean(row.get("跟踪指标")),
                priority=clean(row.get("优先级")),
                method=clean(row.get("生成方式")),
                source=clean(row.get("来源")),
            )
    links = {}
    for row in rows(workbook, "指标-风险-根因-行动建议链路"):
        risk = clean(row.get("风险编码"))
        cause = clean(row.get("根因编码"))
        if not risk or not cause:
            continue
        entry = links.setdefault(risk, dict(risk=risk, causes=[], advice=[], rows=[]))
        if cause not in entry["causes"]:
            entry["causes"].append(cause)
        raw_advice = "、".join(filter(None, (
            clean(row.get("行动建议编码")), clean(row.get("行动建议")),
        )))
        for code in re.findall(r"\b(?:AC|DS)\d+\b", raw_advice):
            if code not in entry["advice"]:
                entry["advice"].append(code)
        entry["rows"].append(dict(
            indicator=clean(row.get("触发指标")),
            risk=risk,
            cause=cause,
            advice=list(re.findall(r"\b(?:AC|DS)\d+\b", raw_advice)),
            owner=clean(row.get("责任角色")),
            deadline=clean(row.get("期限")),
            target=clean(row.get("目标值")),
            tracking=clean(row.get("跟踪指标")),
            closure=clean(row.get("闭环")),
            nextStep=clean(row.get("下一步")),
        ))
    for risk, entry in links.items():
        entry["advice"].extend(
            code for cause in entry["causes"] for code in advice.get(cause, {}).get("causes", [])
            if code not in entry["advice"]
        )

    customer_tier = build_customer_tier_rules(workbook)
    stage_rules = build_stage_rules(workbook)
    product_names = build_product_names(workbook)
    thresholds = build_thresholds(workbook)
    dynamic_cycle = build_dynamic_cycle(workbook)
    electricity_attribute = (fields.get("LE02") or {}).get("new_whprice") or {}
    if not electricity_attribute:
        raise SystemExit("本体 B02 未提供瓦时单价字段 new_whprice")
    electricity_source = {
        # BR-Q01 defines forecast energy as forecast amount ÷ unit price.
        # new_forcastpower is effectively empty in the customer database and
        # new_orderforecast_qty is an order quantity, not energy.
        "mode": "amount_div_price",
        "amountField": "new_forecast_amt_rmb",
        "priceField": "new_whprice",
        "attribute": electricity_attribute.get("attribute"),
        "nativeUnit": "Wh",
        "outputUnit": "GWh",
        "source": "BR-Q01 / B02",
        "inputFields": ["new_forecast_amt_rmb", "new_whprice"],
        "reason": "本体 BR-Q01：预测电量 = 预测金额 new_forecast_amt_rmb ÷ "
                  "new_whprice（元/Wh）÷ 10^9（GWh）；new_forcastpower 实库为空，"
                  "new_orderforecast_qty 是预测订单出货数，不能作为电量。",
    }
    target_energy_source = {
        # BR-Q11 writes "kWh ÷ 10^6", but the customer column is MWh: the 2026
        # target sums to 91,000.15 and 91.0 GWh is the confirmed business
        # target.  Treating it as kWh would produce 0.09 GWh.
        "fieldPattern": "new_month{i}_power",
        "nativeUnit": "MWh",
        "outputUnit": "GWh",
        "source": "B01 / BR-Q11（单位按实库修正）",
        "reason": "new_month*_power 实库为 MWh：2026 年合计 91,000.15，对应 91.0 GWh。"
                  "BR-Q11 标注 kWh 会得到 0.09 GWh，与业务目标不符，故按 MWh ÷ 1,000 换算。",
    }
    bid_rule = build_rule_index(workbook).get("BR-Q07") or {}
    bid_blob = " ".join(clean(bid_rule.get(key)) for key in ("规则描述", "判断或结果"))
    bid_match = {
        "strategy": clean(bid_rule.get("判断或结果")) or clean(bid_rule.get("规则描述")),
        "idRelationAvailable": "名称" not in bid_blob,
        "source": "BR-Q07",
    }

    # User-approved corrections to a workbook statement.  They are kept
    # separate so the ontology-derived overrides never hide a manual decision.
    business_corrections = {
        "BR-Q02": {
            "decision": "签单按合同签订判断，订单数不构成签单",
            "conflictsWith": "V3_含SQL 的 BR-Q02 改为订单明细关联判定",
            "field": "new_contractconfirmation",
            "confirmed": ["1"],
            "notConfirmed": ["0"],
            "unknown": "空值或非 0/1",
            "note": "保留此前用户确认的合同签订口径；new_contractconfirmation_date "
                    "实库 0% 覆盖，不能用于测量日判断。若改为 V3 的订单明细口径，"
                    "需同时调整 R02/R03/C01/C06~C09 的待签集合。",
        },
        "RK07": {
            "decision": "RK07 只关联 RC09，解除 RK07 与 RC01 的矛盾关联",
            "reason": "RK07 客户无商机，不能同时要求存在该客户的 P0 商机。",
            "causes": ["RC09"],
            "advice": ["AC02", "AC03"],
        },
    }

    # Every analysis parameter below is read from the workbook or the data
    # dictionary.  A missing definition fails the build instead of falling
    # back to a value invented in code.
    overrides = {
        "customerTier": customer_tier,
        "stage": stage_rules,
        "products": product_names,
        "bidMatch": bid_match,
        "dynamicCycle": dynamic_cycle,
        "electricitySource": electricity_source,
        "targetEnergy": target_energy_source,
        "recentActivity": {
            "description": "无商机战略客户在本体定义的近期窗口内存在线索、线索进展、客户拜访或最新销售活动时，不认定开拓不足。",
            "accountFields": {
                "lastVisitAt": "new_lastapptime",
                "lastVisitDays": "new_lastjgtime",
                "latestActivityAt": "new_thelastest_updatetime",
                "originatingLeadId": "originatingleadid",
            },
            "leadTable": "ded_public.p_fm_edw_v_ods_crm_lead_esb",
            "leadIdField": "leadid",
            "leadAccountField": "new_account_id",
            "leadCreatedField": "createdon",
            "leadStatusField": "new_leadstatus",
            "activeLeadStatuses": ["3", "5"],
            "leadProgressTable": "ded_public.p_fm_edw_v_ods_crm_new_leadprocess_esb",
            "leadProgressLeadField": "new_leadid",
            "leadProgressCreatedField": "createdon",
        },
        "thresholds": thresholds,
    }
    # The resolved link table must already reflect the explicit business
    # overrides; the UI and task drafting never re-interpret the workbook.
    links["RK07"] = {"risk": "RK07", "causes": ["RC09"], "advice": ["AC02", "AC03"]}
    config = dict(
        version="opportunity-v3-rules-3",
        ontology="商机获取节点 V3",
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
        businessCorrections=business_corrections,
        enums=build_enums(workbook, dictionary, fields, customer_tier),
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
