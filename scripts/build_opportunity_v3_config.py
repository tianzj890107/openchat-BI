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
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能本体文件_1117.xlsx"
DICTIONARY = ROOT / "docs/亿纬锂能/ded_public_数据湖视图数据字典_对齐CRM版_20261111.xlsx"
OUTPUT = ROOT / "bi_agent/cockpit/assets/opportunity-v3/config.json"

# 交付快照 2025-10-31：看板分析时间固定为 2025 年 10 月，SQL 的观察时点也
# 固定在该日 23:59:59，而不是执行时的 CURRENT_TIMESTAMP。统计期间仍是
# 2025 全年（start_date 2025-01-01，end_exclusive 2026-01-01），由
# LEAST(observed_at, end_exclusive) 把 cutoff 截到 10 月 31 日，得到
# “2025 年截至 10 月 31 日”的 YTD 口径。
SNAPSHOT_DATE = "2025-10-31"
OBSERVED_AT = f"{SNAPSHOT_DATE} 23:59:59"
_OBSERVED_AT_RE = re.compile(
    r"(?:CAST\(\s*CURRENT_TIMESTAMP\s+AS\s+TIMESTAMP\s*\)|CURRENT_TIMESTAMP(?:::timestamp)?)")
_PINNED_OBSERVED = f"TIMESTAMP '{OBSERVED_AT}'"


def pin_sql_snapshot(sql):
    """Pin the observed timestamp of a metric SQL to the delivery snapshot.

    Every metric SQL starts from the same ``parameters`` CTE; only the observed
    timestamp moves, so the YTD range keeps its year bounds and the cutoff
    truncates at the snapshot date.  A SQL with no observed timestamp, or one
    that names several, is left untouched instead of being rewritten blindly.
    """
    if not sql or "observed_at" not in sql:
        return sql
    pinned, count = _OBSERVED_AT_RE.subn(_PINNED_OBSERVED, sql)
    return pinned if count == 1 else sql


FIELD_NAMES = {
    "LE01": [
        "opportunityid", "name", "parentaccountid", "new_accountlevel",
        "new_accproducttype", "new_processstage", "new_approvalstatus_acneed",
        "new_approvalstatus", "new_opportunitystatus", "new_contractconfirmation",
        "new_demandinput",
        "new_contractconfirmation_date", "createdon", "new_stage1enddate",
        "new_stage2enddate", "new_stage3enddate", "new_stage4enddate",
        "new_stage5enddate", "ownerid", "statecode", "estimatedvalue",
        "new_projectpower", "new_forecasttime", "modifiedon",
    ],
    "LE02": [
        "new_oppmonthid", "new_opportunity_id", "new_accountdate",
        "new_forecast_amt_rmb", "new_amt_rmb", "new_forcastpower",
        "new_whprice", "new_orderforecast_qty", "statecode", "new_approvalstatus",
        "createdon", "modifiedon",
    ],
    "LE04": [
        "new_projectprocessid", "new_opportunity_id", "new_desc", "new_sdate",
        "new_edate", "new_question_resource", "new_projectstage",
    ],
    "LE05": [
        "accountid", "name", "new_accountlevel", "createdon", "statecode",
        "new_lastapptime", "new_lastjgtime", "new_thelastest_updatetime",
        "originatingleadid", "modifiedon", "owninguser",
    ],
    "LE06": [
        "new_targetid", "new_year", "new_account_id", "new_producttype_id",
        "new_dept_id", "new_opportunity_id", "new_project_name", "statecode", "createdon",
        *[f"new_month{i}" for i in range(1, 13)],
        *[f"new_month{i}_quantity" for i in range(1, 13)],
        *[f"new_month{i}_power" for i in range(1, 13)],
    ],
    "LE07": ["salesorderid", "new_contract_num", "new_contract_amt", "statecode", "statuscode"],
    "LE08": ["salesorderdetailid", "salesorderid", "new_opportunity_id", "new_product_type", "quantity"],
    "LE10": ["teamid", "name"],
    "LE11": ["teamid", "systemuserid"],
    "LE12": ["new_product_typeid", "new_accproducttype", "new_name", "new_product_type_code"],
}


# 投标部分不进入本卡片（用户 2026-11-12 指示）：这些指标、规则、风险、根因和
# 只对应被删根因的行动建议不进入运行配置，链路中对它们的引用一并摘除。
# 自“无投标·周期红字同步版”起本体已不含这些条目和投标表 LE09；清单继续
# 保留，既记录排除范围，也防止旧版本体重新带入。
EXCLUDED = {
    "topic": "投标",
    "reason": "投标部分暂时从销售额口径明细卡片删除（2026-11-12 用户指示）",
    "metrics": ["R10", "R11", "C02", "S03"],
    "rules": ["BR-Q07", "BR-A08", "BR-A09", "BR-C02"],
    "risks": ["RK08", "RK09"],
    "causes": ["RC02"],
    "advice": ["AC04", "AC05"],
}


def apply_exclusion(sections, links):
    """Drop the excluded items and every list reference to them."""
    removed = set()
    absent = []
    for kind in ("metrics", "rules", "risks", "causes", "advice"):
        for code in EXCLUDED[kind]:
            removed.add(code)
            if code in sections[kind]:
                sections[kind].pop(code)
            else:
                absent.append(code)

    def keep(values):
        return [value for value in values if not (isinstance(value, str) and value in removed)]

    for items in sections.values():
        for item in items.values():
            for key, value in list(item.items()):
                if isinstance(value, list):
                    item[key] = keep(value)
    for risk in list(links):
        if risk in removed:
            links.pop(risk)
            continue
        entry = links[risk]
        entry["causes"] = keep(entry.get("causes") or [])
        entry["advice"] = keep(entry.get("advice") or [])
        if "rows" in entry:
            entry["rows"] = [row for row in entry["rows"] if row.get("cause") not in removed]
            for row in entry["rows"]:
                if isinstance(row.get("advice"), list):
                    row["advice"] = keep(row["advice"])
    result = dict(EXCLUDED)
    result["absentInOntology"] = absent
    return result


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
    """Read risk thresholds from the ontology's rule and risk text.

    No threshold is duplicated in code.  A threshold whose rule the ontology
    still carries must parse, or the build fails and names it; a rule the
    ontology has removed (1117: BR-A02 / A05 / A10, BR-C05 / C06 with their
    risks and causes) yields no key, and the runtime does not judge it.
    """
    rules = build_rule_index(workbook)
    risk_levels = {clean(row.get("风险编码")): clean(row.get("风险等级规则")) for row in rows(workbook, "风险")}

    def result(code):
        row = rules.get(code)
        return (clean(row.get("判断或结果")) or clean(row.get("规则描述"))) if row else ""

    a01 = result("BR-A01")
    if not a01:
        raise SystemExit("本体缺少业务规则：BR-A01")
    thresholds, sources = {}, {}

    def put(key, value, source, scale=1):
        thresholds[key] = value / scale
        sources[key] = source

    put("gapRateHigh", int(_match(r"缺口率\s*≥\s*(\d+)%", a01, "BR-A01 缺口率高阈值").group(1)), "BR-A01", 100)
    put("gapRateMedium", int(_match(r"(\d+)%\s*[~～–-]\s*\d+%\s*中", a01, "BR-A01 缺口率中阈值").group(1)),
        "BR-A01", 100)
    a02 = result("BR-A02")
    if a02:
        put("signLagExtremePoints", int(_match(r"≥\s*(\d+)\s*为极高", a02, "BR-A02 签单落后极高阈值").group(1)), "BR-A02")
        put("signLagHighPoints", int(_match(r"≥\s*(\d+)\s*且\s*[＜<]\s*\d+\s*为高", a02,
                                           "BR-A02 签单落后高阈值").group(1)), "BR-A02")
        put("annualCoverageRatio", int(_match(r"全年金额覆盖率\s*[＜<]\s*(\d+)%", a02,
                                              "BR-A02 全年金额覆盖率预警").group(1)), "BR-A02", 100)
    a05 = result("BR-A05")
    if a05:
        put("productRiskAmountHigh", int(_match(r"≥\s*(\d+)\s*亿元\s*为?高", a05, "BR-A05 待签高阈值").group(1)), "BR-A05")
        put("productRiskAmountMedium", int(_match(r"≥\s*(\d+)\s*且\s*[＜<]\s*\d+\s*亿元\s*为?中", a05,
                                                 "BR-A05 待签中阈值").group(1)), "BR-A05")
        put("productGapRate", int(_match(r"缺口率[^。；]*?[＞>]\s*(\d+)%\s*时触发", a05,
                                         "BR-A05 全年目标缺口率门槛").group(1)), "BR-A05", 100)
    a10 = result("BR-A10")
    if a10:
        put("impactAmountHigh", int(_match(r"影响预测\s*≥\s*(\d+)\s*亿元", a10, "BR-A10 影响金额高阈值").group(1)),
            "BR-A10")
    # BR-A11 / RK11 等级：覆盖 ≥ 2 个阶段为高，否则按跨阶段去重影响金额 ≥ 10 亿元为高。
    # 1117 版把分档写在风险表“风险等级规则”中，旧版写在 BR-A11。
    band_text = " ".join(filter(None, (result("BR-A11"), risk_levels.get("RK11", ""))))
    if result("BR-A11"):
        put("stageBandStagesHigh", int(_match(r"(?:覆盖|至少)\s*≥?\s*(\d+)\s*个阶段", band_text,
                                              "BR-A11 超期阶段数高阈值").group(1)), "BR-A11")
        put("stageBandAmountHigh", int(_match(r"(?:预测金额合计\s*≥|≥)\s*(\d+)\s*亿元\s*(?:为)?高", band_text,
                                              "BR-A11 超期预测金额高阈值").group(1)), "BR-A11")
    for key, code, pattern, label in (
            ("productPendingRatio", "BR-C05", r"≥\s*(\d+)%", "BR-C05 产品待签占比"),
            ("focusTrackingRatio", "BR-C06", r"<\s*(\d+)%", "BR-C06 重点跟踪占比"),
            ("otherPendingRatio", "BR-C07", r"≥\s*(\d+)%", "BR-C07 其余占比")):
        text = result(code)
        if text:
            put(key, int(_match(pattern, text, label).group(1)), code, 100)
    thresholds["sources"] = sources
    return thresholds


def build_stage_baselines(workbook):
    """1117 BR-Q06: fixed stage baselines (P0=32.6 …); empty for older versions."""
    row = build_rule_index(workbook).get("BR-Q06") or {}
    blob = " ".join(clean(row.get(key)) for key in ("规则描述", "触发条件", "判断或结果"))
    found = dict(re.findall(r"(P[0-4])\s*[=＝]\s*([0-9]+(?:\.[0-9]+)?)", blob))
    return {stage: float(value) for stage, value in found.items()}


def build_cause_analysis(workbook, causes):
    """How root causes are produced, read from the cause sheet and BR-L01.

    When every cause's 判定方式 is AI the card runs one global model analysis
    over the established risks (BR-L01) instead of matching the cause sheet;
    the per-risk count comes from the rule text, e.g. “1～2 条根因”.
    """
    methods = {cause["method"] for cause in causes.values()}
    if methods != {"AI"}:
        return {"mode": "ontology", "source": "根因.判定方式"}
    row = build_rule_index(workbook).get("BR-L01") or {}
    text = " ".join(clean(row.get(key)) for key in ("规则描述", "判断或结果"))
    # “每条风险给出 1～2 条根因” / 1117：“每条已成立风险输出1～2条有指标支撑、待核实的原因”。
    found = _match(r"(\d+)\s*[～~–-]\s*(\d+)\s*条(?:根因|[^。；]{0,20}?原因)", text, "BR-L01 每条风险根因数")
    return {
        "mode": "ai",
        "minPerRisk": int(found.group(1)),
        "maxPerRisk": int(found.group(2)),
        "source": "BR-L01 / 根因.判定方式",
        "description": clean(row.get("规则描述")),
    }


def build_dynamic_cycle(workbook):
    rules = build_rule_index(workbook)
    row = rules.get("BR-Q06") or {}
    blob = " ".join(clean(row.get(key)) for key in ("规则描述", "触发条件", "判断或结果"))
    found = re.search(r"[×xX*]\s*([0-9.]+)", blob)
    if not found:
        # 1117 版用固定阶段基线，严重超期为 ≥ 1.5 倍基线（BR-V08）。
        found = _match(r"([0-9.]+)\s*倍", " ".join(
            clean(build_rule_index(workbook).get("BR-V08", {}).get(key)) for key in ("规则描述", "判断或结果")),
            "BR-Q06 / BR-V08 周期倍数")
    multiplier = float(found.group(1))
    return {
        "multiplier": multiplier,
        "strict": "严格大于" in blob,
        # BR-Q06: the stage mean counts only samples with a real start and
        # end; an unfinished stage is compared with it but never averaged in.
        "completedOnly": any(phrase in blob for phrase in ("仅统计完整有效起止", "只计完整", "不计未结束在途")),
        "sample": clean(row.get("判断或结果")) or clean(row.get("规则描述")),
        "source": "BR-Q06",
    }


def build_storage_scope(workbook):
    """BR-Q04 储能客户范围: which customers the customer metrics cover."""
    rules = build_rule_index(workbook)
    row = rules.get("BR-Q04") or {}
    description = clean(row.get("规则描述"))
    related = clean(row.get("关联本体元素"))
    # 旧版写“储能客户范围：…”，1117 版写“储能范围沿当前商机负责人→团队人员→…”。
    marker = next((item for item in ("储能客户范围：", "储能范围") if item in description), "")
    if not marker:
        return {"enabled": False, "source": "BR-Q04"}
    scope_line = _match(r"储能客户范围适用：([^\n。]+)", related, "BR-Q04 储能客户范围适用指标").group(1)
    metrics = re.findall(r"[A-Z]\d{2}", scope_line)
    if not metrics:
        raise SystemExit("本体 BR-Q04 未列出储能客户范围适用指标")
    return {
        "enabled": True,
        "rule": description[description.index(marker):],
        "metrics": list(dict.fromkeys(metrics)),
        "ownerField": "ownerid",
        "accountOwnerField": "owninguser",
        "source": "BR-Q04",
    }


def build_stage_rules(workbook):
    stages = {}
    for row in rows(workbook, "维度派生规则"):
        if clean(row.get("维度编码")) != "D_STAGE":
            continue
        expression = clean(row.get("规则表达式"))
        match = re.search(r"new_processstage\s*=\s*'([^']+)'", expression)
        if match:
            stages[match.group(1)] = clean(row.get("维度枚举值名称"))
            continue
        # 1117 版：截至阶段由阶段结束时间链推断，new_processstage 只作原始字段；
        # 运行时仍需 P0～P4 的原始枚举映射，按序号 1～5 对应 11～15。
        order = clean(row.get("序号"))
        if not order.isdigit():
            raise SystemExit(f"本体阶段规则无法解析：{expression}")
        stages[str(10 + int(order))] = clean(row.get("维度枚举值名称"))
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
        "status": "pending" if pending else "confirmed",
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
                category=clean(row.get("分类")),
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
                sql=pin_sql_snapshot(clean(row.get("调用SQL"))),
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
                relatedElements=clean(row.get("关联本体元素")),
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
    # B01 / BR-Q11: the target energy comes from new_month1_power..12_power and
    # is converted with the ontology SQL's own parameter
    # target_power_units_per_gwh (kWh ÷ 10^6).  The value is read from the
    # workbook, never written here, and every target metric must agree.
    units = {}
    for code, metric in metrics.items():
        sql = metric.get("sql") or ""
        if "target_power_units_per_gwh" not in sql:
            continue
        found = re.findall(
            r"(?:CAST\(\s*(\d+)\s+AS\s+(?:DECIMAL|NUMERIC)\s*\)|(\d+)\s*::\s*numeric)\s+AS\s+target_power_units_per_gwh",
            sql, flags=re.I)
        values = {int(a or b) for a, b in found}
        if len(values) != 1:
            raise SystemExit(f"本体 {code} 的 target_power_units_per_gwh 无法解析：{sorted(values)}")
        units[code] = values.pop()
    if "B01" not in units or len(set(units.values())) != 1:
        raise SystemExit(f"本体目标电量换算系数缺失或不一致：{units}")
    if "new_month1_power" not in (metrics["B01"].get("sql") or ""):
        raise SystemExit("本体 B01 未使用 new_month*_power 作为目标电量")
    units_per_gwh = units["B01"]
    target_energy_source = {
        "fieldPattern": "new_month{i}_power",
        "unitsPerGwh": units_per_gwh,
        "nativeUnit": {1_000_000: "kWh", 1_000: "MWh", 1: "GWh"}.get(units_per_gwh, ""),
        "outputUnit": "GWh",
        "source": "B01 调用SQL parameters.target_power_units_per_gwh / BR-Q11",
        "metrics": sorted(units),
    }
    # User-approved corrections to a workbook statement.  They are kept
    # separate so the ontology-derived overrides never hide a manual decision.
    business_corrections = {
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
        "dynamicCycle": dynamic_cycle,
        "storageCustomerScope": build_storage_scope(workbook),
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
        "stageBaselines": build_stage_baselines(workbook),
        "causeAnalysis": build_cause_analysis(workbook, causes),
    }
    # The resolved link table must already reflect the explicit business
    # overrides; the UI and task drafting never re-interpret the workbook.
    if "RK07" in risks:
        links["RK07"] = {"risk": "RK07", "causes": ["RC09"], "advice": ["AC02", "AC03"]}
    excluded = apply_exclusion(
        dict(metrics=metrics, rules=rules, risks=risks, causes=causes, advice=advice), links)
    for code, risk in risks.items():
        categories = {metric["category"] for metric in metrics.values()
                      if code in metric["risks"] and metric["category"]}
        if len(categories) != 1:
            raise SystemExit(f"本体 {code} 未找到唯一的关联指标分类：{sorted(categories)}")
        risk["category"] = categories.pop()
    config = dict(
        version="opportunity-v3-rules-14",
        ontology="商机获取节点 V3 本体文件_1117（第三版执行口径）",
        source=dict(path=SOURCE.relative_to(ROOT).as_posix(), sha256=digest(SOURCE)),
        dictionary=dict(path=DICTIONARY.relative_to(ROOT).as_posix(), sha256=digest(DICTIONARY)),
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
        excluded=excluded,
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
