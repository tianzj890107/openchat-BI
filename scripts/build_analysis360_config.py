"""Build the 360 智能分析 runtime config from the 流程360全局本体 workbook.

The 360 analysis agent reads only this config: activities, metrics, rules,
risks, causes, advice, the risk chain, evidence / recheck requirements, entity
relations and the registered queries with their SQL.  Nothing here is typed by
hand; a workbook statement that cannot be read fails the build.

    python scripts/build_analysis360_config.py
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
import re

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/亿纬锂能/亿纬锂能_流程360全局本体_无投标_V1.0.xlsx"
TARGET = ROOT / "bi_agent/analysis360/assets/global-ontology.json"
VERSION = "analysis360-global-1"
ONTOLOGY = "亿纬锂能_流程360全局本体_无投标_V1.0"


def clean(value):
    return "" if value is None else str(value).strip()


def codes(value):
    """Split a cell such as "R01、B01\\nB02" into its codes."""
    return [item for item in re.split(r"[、,，;；\s]+", clean(value)) if item and item != "—"]


def leading_codes(value):
    """Codes of a cell whose entries are "CODE 名称" lines."""
    found = []
    for line in re.split(r"[\n、]+", clean(value)):
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_\-]*)", line)
        if match:
            found.append(match.group(1))
    return list(dict.fromkeys(found))


def sheet(workbook, name):
    rows = workbook[name].iter_rows(values_only=True)
    header = [clean(cell) for cell in next(rows)]
    result = []
    for row in rows:
        if not any(cell is not None and clean(cell) for cell in row):
            continue
        result.append({key: clean(value) for key, value in zip(header, row) if key})
    return result


def build():
    workbook = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)

    entities = {}
    for row in sheet(workbook, "逻辑实体"):
        entities[row["逻辑实体编码"]] = dict(code=row["逻辑实体编码"], name=row["逻辑实体名称"],
                                           english=row["逻辑实体英文名"], object=row["业务对象编码"],
                                           objectName=row["业务对象名称"], definition=row["逻辑实体定义"])
    for row in sheet(workbook, "逻辑实体映射"):
        entity = entities.get(row["逻辑实体编码"])
        if entity is not None:
            entity["table"] = row["关联物理表"]
            entity["status"] = row["状态"]

    attributes = defaultdict(dict)   # entity → english → attribute
    attribute_by_code = {}
    for row in sheet(workbook, "业务属性"):
        item = dict(code=row["业务属性编码"], name=row["业务属性名称"], english=row["业务属性英文名称"],
                    type=row["数据类型"], primaryKey=row["是否物理主键"] == "Y")
        attributes[row["逻辑实体编码"]][item["english"]] = item
        attribute_by_code[item["code"]] = dict(item, entity=row["逻辑实体编码"])
    for row in sheet(workbook, "业务属性映射"):
        item = attribute_by_code.get(row["业务属性编码"])
        if item is not None:
            item["column"] = row["来源字段"]
            attributes[item["entity"]][item["english"]]["column"] = row["来源字段"]

    relations = {}
    for row in sheet(workbook, "实体关系"):
        code = row["关系编码"]
        source, target = entities.get(row["源逻辑实体编码"]), entities.get(row["目标逻辑实体编码"])
        source_attr = attribute_by_code.get(row["源关联属性编码"]) or {}
        target_attr = attribute_by_code.get(row["目标关联属性编码"]) or {}
        kind = row["关系分类"]
        reason = ""
        if "候选" in kind:
            reason = "候选引用，未通过验收"
        elif not (source and target and source.get("table") and target.get("table")):
            reason = "缺少物理表映射"
        elif not (source_attr.get("column") and target_attr.get("column")):
            reason = "缺少关联字段映射"
        relations[code] = dict(
            code=code, name=row["关系中文名称"], kind=kind, cardinality=row["关系基数"],
            source=row["源逻辑实体编码"], sourceName=row["源逻辑实体名称"],
            target=row["目标逻辑实体编码"], targetName=row["目标逻辑实体名称"],
            sourceColumn=source_attr.get("column", ""), targetColumn=target_attr.get("column", ""),
            description=row["关系描述"], enabled=not reason, disabledReason=reason)

    activities = {}
    for row in sheet(workbook, "流程活动"):
        activities[row["活动编码"]] = dict(
            code=row["活动编码"], name=row["活动"], process=row["流程编码"], processName=row["流程名称"],
            role=row["责任角色"], objects=codes(row["业务对象"]), io=row["输入→输出"],
            boundary=row["运行边界"], upstream=leading_codes(row["上游活动"]),
            evidenceRule=row["跨环节取证要求"])

    metrics = {}
    for row in sheet(workbook, "指标"):
        metrics[row["指标编码"]] = dict(
            code=row["指标编码"], name=row["指标名称"], node=row["所属节点"], category=row["分类或阶段"],
            definition=row["指标定义"], rule=row["业务规则"], unit=row["统计单位"],
            resultColumn=row["结果列"], dimensions=codes(row["适用维度"]),
            status=row["SQL实现状态"], risks=codes(row["触发风险"]), note=row["核对说明"])

    rules = {}
    for row in sheet(workbook, "业务规则"):
        rules[row["规则编码"]] = dict(
            code=row["规则编码"], name=row["规则名称"], description=row["规则描述"],
            trigger=row["触发条件"], result=row["判断或结果"], action=row["处置动作"],
            category=row["规则类别"], related=row["关联本体元素"])

    risks = {}
    for row in sheet(workbook, "风险"):
        risks[row["风险编码"]] = dict(
            code=row["风险编码"], name=row["风险名称"], description=row["风险描述"], node=row["节点"],
            indicators=codes(row["触发指标"]), rule=row["异常判定规则"], condition=row["成立条件"],
            levelRule=row["风险等级规则"], objects=row["影响对象"], causes=codes(row["候选根因"]))

    causes = {}
    for row in sheet(workbook, "根因"):
        causes[row["根因编码"]] = dict(
            code=row["根因编码"], name=row["根因名称"], group=row["根因分组"], risks=codes(row["关联风险"]),
            indicators=codes(row["判定指标"]), rule=row["根因成立规则"], condition=row["成立条件"],
            method=row["判定方式"], aiFocus=row["AI 分析要点"], output=row["输出"],
            advice=codes(row["行动建议编码"]))

    advice = {}
    for row in sheet(workbook, "行动建议"):
        advice[row["行动建议编码"]] = dict(
            code=row["行动建议编码"], causes=codes(row["对应根因"]), name=row["行动建议"],
            content=row["行动内容"], objects=row["作用对象"], role=row["责任角色"], deadline=row["期限"],
            target=row["目标值"], acceptance=row["验收标准"], tracking=codes(row["跟踪指标"]),
            priority=row["优先级"])

    links = []
    for row in sheet(workbook, "指标-风险-根因-行动建议链路"):
        links.append(dict(
            code=row["链路编号"], indicators=leading_codes(row["触发指标"]), rule=row["异常判定规则"],
            risk=row["风险编码"], cause=row["根因编码"], causeIndicators=leading_codes(row["判定指标"]),
            causeRule=row["根因成立规则"], method=row["判定方式"], advice=row["行动建议编码"],
            role=row["责任角色"], deadline=row["期限"], tracking=leading_codes(row["跟踪指标"]),
            closure=row["闭环"], next=row["下一步"]))

    evidence = []
    risk_activity = {}
    for row in sheet(workbook, "证据与复检"):
        evidence.append(dict(
            risk=row["风险"], activity=row["流程活动"], cause=row["根因"], required=row["必须收集的证据"],
            confirm=row["确认或反证条件"], grain=row["证据对象粒度"], recheck=codes(row["复检指标"]),
            close=row["关闭条件"], queries=codes(row["可用查询索引"]), gate=row["启用门槛"]))
        risk_activity.setdefault(row["风险"], row["流程活动"])
    # A risk without an evidence row is placed by its node name.
    for code, risk in risks.items():
        if code in risk_activity:
            continue
        match = next((activity["code"] for activity in activities.values()
                      if activity["processName"] and activity["processName"] in risk["node"]), "")
        if not match:
            raise SystemExit(f"风险 {code} 无法归属流程活动：节点 {risk['node']}")
        risk_activity[code] = match
    for code, risk in risks.items():
        risk["activity"] = risk_activity[code]

    constraints = defaultdict(list)
    for row in sheet(workbook, "接入与范围"):
        for index in codes(row["对象／查询索引"]):
            constraints[index].append(dict(type=row["类型"], fact=row["事实及原因"], rule=row["处理约束"]))

    shards = defaultdict(list)
    for row in sheet(workbook, "SQL原文分片"):
        shards[row["查询索引"]].append((int(row["分片序号"]), int(row["总分片数"]), row["SQL原文"]))
    # openpyxl strips nothing from the SQL cells; re-read them raw so the
    # hash matches the registered original.
    raw = openpyxl.load_workbook(SOURCE, read_only=True, data_only=True)["SQL原文分片"]
    shards = defaultdict(list)
    rows = raw.iter_rows(values_only=True)
    next(rows)
    for row in rows:
        if row[0]:
            shards[str(row[0]).strip()].append((int(row[1]), int(row[2]), "" if row[4] is None else str(row[4])))

    bindings = defaultdict(list)
    for row in sheet(workbook, "查询输出绑定"):
        bindings[row["查询索引"]].append(dict(code=row["指标／维度编码"], type=row["类型"], label=row["显示名"],
                                            role=row["角色"], column=row["输出列编码"]))
    sources = defaultdict(list)
    for row in sheet(workbook, "查询来源实体"):
        if row["逻辑实体"] and row["逻辑实体"] not in sources[row["查询索引"]]:
            sources[row["查询索引"]].append(row["逻辑实体"])

    queries, sql = {}, {}
    for row in sheet(workbook, "查询注册"):
        index = row["查询索引"]
        parts = sorted(shards.get(index) or [])
        if not parts or len(parts) != parts[0][1] or [part[0] for part in parts] != list(range(1, len(parts) + 1)):
            raise SystemExit(f"查询 {index} 的 SQL 原文分片不完整")
        text = "".join(part[2] for part in parts)
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != row["SHA-256"]:
            raise SystemExit(f"查询 {index} 的 SQL 原文与登记哈希不一致")
        kinds = {item["type"] for item in constraints.get(index, [])}
        status = row["使用状态"]
        if "范围隔离" in kinds:
            gate, reason = "isolated", "已隔离：整条查询含范围外逻辑，不得进入候选集"
        elif row["来源启用"] == "待验收":
            gate, reason = "pending", "新增诊断查询，待业务与客户库验收后启用"
        elif "配置依赖" in kinds or "MOCK" in status.upper():
            gate, reason = "mock", "依赖 MOCK 配置，只作回放参考，不能作为生产结论"
        else:
            gate, reason = "enabled", ""
        try:
            contract = json.loads(row["筛选契约JSON"] or "{}")
        except json.JSONDecodeError as exc:
            raise SystemExit(f"查询 {index} 的筛选契约不是合法 JSON：{exc}")
        queries[index] = dict(
            index=index, key=row["配置键／调用键"], type=row["查询类型"], origin=row["来源启用"],
            mode=("template" if index.startswith("T") else "diagnostic" if index.startswith("N") else "config"),
            metrics=codes(row["结果指标"]), dimensions=codes(row["结果维度"]), contract=contract,
            params=codes(row["实际SQL参数"]), sources=row["物理源"], entities=sources.get(index, []),
            status=status, note=row["口径说明"], sha256=row["SHA-256"], updatedAt=row["最近更新"],
            gate=gate, gateReason=reason, constraints=constraints.get(index, []),
            outputs=bindings.get(index, []))
        sql[index] = text

    for name, group in (("活动", activities), ("指标", metrics), ("风险", risks), ("根因", causes),
                        ("查询", queries)):
        if not group:
            raise SystemExit(f"全局本体缺少{name}")
    config = dict(
        version=VERSION, ontology=ONTOLOGY,
        source=dict(file=str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
                    sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest()),
        budget=dict(maxEntityHops=3, maxCausesPerRound=5, maxQueries=12, previewRows=100),
        activities=activities, metrics=metrics, rules=rules, risks=risks, causes=causes, advice=advice,
        links=links, evidence=evidence, entities=entities,
        attributes={entity: values for entity, values in attributes.items()},
        relations=relations, queries=queries, sql=sql)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(config, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                      encoding="utf-8")
    gates = defaultdict(int)
    for query in queries.values():
        gates[query["gate"]] += 1
    print(f"wrote {TARGET.relative_to(ROOT)}")
    print(f"activities={len(activities)} metrics={len(metrics)} risks={len(risks)} causes={len(causes)} "
          f"advice={len(advice)} links={len(links)} evidence={len(evidence)} relations={len(relations)} "
          f"queries={len(queries)} gates={dict(gates)}")


if __name__ == "__main__":
    build()
