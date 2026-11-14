"""The 360 智能分析 tools: the access strategy's six interfaces.

    G360ResolveScope       resolve_scope        activity, anchors, period, versions
    G360GetSubgraph        get_subgraph         minimal definition-layer subgraph
    G360ExecuteQuery       execute_query        registered queries only, with evidence
    G360DrillRelation      drill_relation       accepted entity relations, by primary key
    G360EvaluateAndRecord  evaluate_and_record  three-state judgement with its evidence
    G360DraftAndRecheck    draft_and_recheck    advice draft and recheck plan

Each web session owns one ``Run``: its scope, budget, evidence and records.
The model never supplies SQL, table names or evidence ids of its own.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import threading

from . import ontology as onto
from .queries import QueryRejected, classify, render

TOOL_NAMES = ["G360ResolveScope", "G360GetSubgraph", "G360ExecuteQuery", "G360DrillRelation",
              "G360EvaluateAndRecord", "G360DraftAndRecheck"]

# assessment status → is_established (RUN05): true / false / unknown
STATUSES = {"成立": True, "未命中": False, "待核实": None, "无法判定": None, "不适用": None, "未评估": None}
_NEED_EVIDENCE = {"成立", "未命中"}
_NEED_REASON = {"待核实", "无法判定", "不适用"}
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _text(value, limit=400):
    return "" if value is None else str(value).strip()[:limit]


def _json(payload):
    return json.dumps(payload, ensure_ascii=False, default=str)


class Run:
    """One 360 analysis session: scope, budget, evidence and judgement records."""

    def __init__(self, handoff=None, database_factory=None, config=None):
        self.config = config or onto.load_config()
        self.handoff = handoff
        self._database_factory = database_factory
        self._database = None
        self.lock = threading.RLock()
        self.scope = None
        self.allowed = set()
        self.queries = 0
        self.evidence = {}
        self.records = []
        self.seq = 0

    # -- helpers ---------------------------------------------------------
    @property
    def budget(self):
        return self.config["budget"]

    def database(self):
        if self._database is None:
            if self._database_factory is None:
                from ..cockpit.opportunity_v2 import _database
                self._database_factory = _database
            self._database = self._database_factory()
        return self._database

    def next_id(self, prefix):
        self.seq += 1
        return f"{prefix}{self.seq:03d}"

    def versions(self):
        return dict(ontology=self.config["ontology"], configVersion=self.config["version"],
                    ontologySha256=self.config["source"]["sha256"][:16])

    # -- resolve_scope ---------------------------------------------------
    def resolve_scope(self, params):
        config = self.config
        anchors, unresolved, notes = [], [], []

        def add(code, source, text=""):
            kind = onto.element_kind(config, code)
            if kind in {"risks", "causes", "metrics"}:
                if not any(a["code"] == code for a in anchors):
                    item = config[kind][code]
                    anchors.append(dict(kind=kind[:-1], code=code, name=item.get("name", ""), source=source,
                                        activity=onto.activity_of(config, kind, code)))
                return True
            candidates = onto.match_by_name(config, text) if text else []
            unresolved.append(dict(code=code, text=text, source=source, candidates=candidates[:5]))
            return False

        # Route priority: trusted card / selected instance → explicit codes →
        # scenario words and metric semantics.
        handoff = self.handoff if params.get("use_handoff", True) else None
        if handoff:
            clause = handoff["clause"]
            add(clause["code"], "卡片条款", clause["title"])
            for code in clause.get("linkedRisks") or []:
                add(code, "卡片关联风险")
            for sibling in handoff.get("siblings") or []:
                add(sibling["code"], "同卡片条款", sibling["title"])
        for code in params.get("anchor_codes") or []:
            add(_text(code, 40), "明确编码")
        phrase = _text(params.get("question"), 300)
        if not anchors and phrase:
            for candidate in onto.match_by_name(config, phrase)[:5]:
                unresolved.append(dict(text=phrase, source="场景词", candidates=[candidate]))
        primary = _text(params.get("primary_code"), 40) or (anchors[0]["code"] if anchors else "")
        if primary and not any(a["code"] == primary for a in anchors):
            add(primary, "明确编码")
        main = next((a for a in anchors if a["code"] == primary), None)
        if main is None:
            return dict(status="needs_clarification",
                        message="未能在全局本体中定位到风险、根因或指标；请从候选中确认一个，或给出明确编码。",
                        unresolved=unresolved, versions=self.versions())

        # Period: explicit request, then the confirmed card filter.
        start, end = _text(params.get("period_start"), 10), _text(params.get("period_end_exclusive"), 10)
        source = "用户明确期间"
        card_period = _text((handoff or {}).get("period"), 10)
        if not (start and end):
            year = _text(params.get("year"), 4) or card_period[:4]
            source = "用户明确年度" if _text(params.get("year"), 4) else "卡片筛选"
            if re.fullmatch(r"\d{4}", year or ""):
                start, end = f"{year}-01-01", f"{int(year) + 1}-01-01"
        period = None
        if start and end:
            try:
                if dt.date.fromisoformat(end) <= dt.date.fromisoformat(start):
                    raise ValueError
            except ValueError:
                return dict(status="needs_clarification", message="期间不合法：需要 YYYY-MM-DD，且结束日晚于开始日。",
                            versions=self.versions())
            observed = _text(params.get("observed_date"), 10) or _text((handoff or {}).get("measurementDate"), 10) \
                or dt.date.today().isoformat()
            period = dict(start=start, endExclusive=end, observedDate=observed, source=source,
                          semantics="统计期间为 [start, endExclusive)；observedDate 是观察日")
            if card_period and source.startswith("用户") and card_period[:4] != start[:4]:
                notes.append(f"显式期间与卡片期间 {card_period} 不一致：这是重开分析，卡片上的数值不再适用。")
        activity = config["activities"].get(main["activity"]) or {}
        kind = main["kind"] + "s"
        with self.lock:
            self.scope = dict(primary=main, anchors=anchors, period=period, activity=main["activity"],
                              channel=_text(params.get("channel"), 12) or "金额与电量分别判断")
            self.allowed = set(onto.allowed_queries(config, kind, main["code"]))
            self.queries = 0
        return dict(
            status="ok" if period else "needs_period",
            message="" if period else "缺少统计期间：请询问用户年度或起止日期后再取数。",
            activity=dict(code=activity.get("code", ""), name=activity.get("name", ""),
                          process=activity.get("process", ""), processName=activity.get("processName", ""),
                          role=activity.get("role", ""), boundary=activity.get("boundary", "")),
            primary=main, anchors=anchors, unresolved=unresolved, period=period,
            channel=self.scope["channel"], notes=notes, versions=self.versions(),
            permission=dict(scope="服务只读账号可见范围", note="当前未接入按组织、客户的行级权限，结果不代表个人授权范围"),
            budget=dict(self.budget, usedQueries=0))

    # -- get_subgraph ----------------------------------------------------
    def get_subgraph(self, params):
        code = _text(params.get("code"), 40) or ((self.scope or {}).get("primary") or {}).get("code", "")
        kind = onto.element_kind(self.config, code)
        if kind not in {"risks", "causes", "metrics"}:
            return dict(status="not_found", message=f"全局本体中没有风险、根因或指标 {code}")
        graph = onto.subgraph(self.config, kind, code)
        queries = onto.allowed_queries(self.config, kind, code)
        with self.lock:
            if self.scope is not None:
                self.allowed |= set(queries)
        relations = [dict(code=item["code"], name=item["name"], source=item["sourceName"], target=item["targetName"],
                          cardinality=item["cardinality"], enabled=item["enabled"],
                          disabledReason=item["disabledReason"])
                     for item in self.config["relations"].values()]
        if kind == "risks" and len(graph["candidateCauses"]) > self.budget["maxCausesPerRound"]:
            graph["note"] = f"每轮最多并行评估 {self.budget['maxCausesPerRound']} 个候选根因，其余标记未评估。"
        return dict(status="ok", subgraph=graph,
                    queries=[onto.query_card(self.config, index) for index in queries],
                    relations=[r for r in relations if r["enabled"]],
                    candidateRelations=[r["code"] for r in relations if not r["enabled"]],
                    versions=self.versions())

    # -- execute_query ---------------------------------------------------
    def execute_query(self, params):
        index = _text(params.get("query_index"), 20)
        if self.scope is None:
            return dict(status="rejected", message="先调用 G360ResolveScope 确定分析范围。")
        query = self.config["queries"].get(index)
        if not query:
            return dict(status="rejected", message=f"未登记的查询：{index}")
        if query["gate"] != "enabled":
            return dict(status="blocked", queryIndex=index, gate=query["gate"],
                        message=query.get("gateReason") or "该查询未启用", note="保留为未取数项，不得用其他数据替代。")
        if index not in self.allowed:
            return dict(status="rejected", queryIndex=index,
                        message="该查询不在当前范围的子图内；先对相关风险、根因或指标调用 G360GetSubgraph。")
        with self.lock:
            if self.queries >= self.budget["maxQueries"]:
                return dict(status="budget_exhausted",
                            message=f"本范围的查询预算（{self.budget['maxQueries']} 次）已用尽；保留已核实结果，其余标记未评估。")
            self.queries += 1
            used = self.queries
        supplied = dict(params.get("params") or {})
        period = self.scope.get("period") or {}
        needs_period = query["mode"] == "template" or any(
            name in {"start_date", "end_exclusive"} for name in onto.query_card(self.config, index)["parameters"])
        if needs_period and period:
            supplied.setdefault("start_date", period["start"])
            supplied.setdefault("end_exclusive", period["endExclusive"])
        if query["mode"] == "template" and period:
            supplied.setdefault("observed_date", period["observedDate"])
        try:
            database = self.database()
            schema = getattr(getattr(database, "config", None), "schema", "ded_public") or "ded_public"
            sql, values, effective, notes = render(self.config, index, supplied, schema)
        except QueryRejected as exc:
            return dict(status="rejected", queryIndex=index, message=str(exc), budgetUsed=used)
        except Exception as exc:  # noqa: BLE001 - configuration, reported without detail
            return dict(status="unavailable", queryIndex=index, message=f"只读数据库不可用：{type(exc).__name__}")
        limit = 2000
        try:
            with database.snapshot() as reader:
                result = reader.run(sql, values or None, max_rows=limit)
        except Exception as exc:  # noqa: BLE001 - classified, never retried with other SQL
            name = type(exc).__name__
            text = str(exc)
            status = ("timeout" if "timeout" in text.lower() or "Timeout" in name or "QueryCanceled" in name
                      else "denied" if "permission" in text.lower() or "InsufficientPrivilege" in name
                      else "error")
            return dict(status=status, queryIndex=index, message=f"{name}：{text[:200]}", budgetUsed=used,
                        note="保留为未取数项并记录原因。")
        rows = [dict(row) for row in result.rows]
        metric_columns = [item["column"] for item in query.get("outputs") or []
                          if item.get("role") == "指标输出" and item.get("column")]
        quality = classify(rows, result.truncated, metric_columns)
        with self.lock:
            evidence_id = self.next_id("E")
            self.evidence[evidence_id] = dict(
                id=evidence_id, kind="query", queryIndex=index, queryKey=query["key"], sha256=query["sha256"],
                sqlHash=hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16], parameters=effective,
                dataAsOf=dt.datetime.now().isoformat(timespec="seconds"), rowCount=len(rows),
                truncated=bool(result.truncated), quality=quality, columns=list(result.columns), rows=rows,
                depth=0, purpose=_text(params.get("purpose"), 200))
        preview = self.budget["previewRows"]
        return dict(
            status=quality, evidenceId=evidence_id, queryIndex=index, queryKey=query["key"],
            sha256=query["sha256"], parameters=effective, columns=list(result.columns),
            outputs=[dict(code=item["code"], label=item["label"], role=item["role"], column=item["column"])
                     for item in query.get("outputs") or [] if item.get("role") in {"指标输出", "返回维度"}],
            rowCount=len(rows), truncated=bool(result.truncated), rows=rows[:preview],
            previewRows=min(len(rows), preview), queryStatus=query.get("status") or "",
            notes=notes + ([f"结果超过 {limit} 行被截断，全量判断须由服务端聚合"] if result.truncated else []),
            budgetUsed=used, budgetLeft=self.budget["maxQueries"] - used)

    # -- drill_relation --------------------------------------------------
    def drill_relation(self, params):
        if self.scope is None:
            return dict(status="rejected", message="先调用 G360ResolveScope 确定分析范围。")
        code = _text(params.get("relation_code"), 20)
        relation = self.config["relations"].get(code)
        if not relation:
            return dict(status="rejected", message=f"全局本体中没有关系 {code}")
        if not relation["enabled"]:
            return dict(status="blocked", relation=code, message=f"关系未验收：{relation['disabledReason']}")
        source_evidence = self.evidence.get(_text(params.get("from_evidence"), 12))
        if not source_evidence:
            return dict(status="rejected", message="from_evidence 必须是本次分析中已有的证据编号。")
        depth = int(source_evidence.get("depth") or 0) + 1
        if depth > self.budget["maxEntityHops"]:
            return dict(status="budget_exhausted", message=f"实体下钻深度上限为 {self.budget['maxEntityHops']} 跳。")
        direction = _text(params.get("direction"), 10) or "forward"
        if direction not in {"forward", "reverse"}:
            return dict(status="rejected", message="direction 只能是 forward 或 reverse")
        target_entity = relation["target"] if direction == "forward" else relation["source"]
        key_column = relation["targetColumn"] if direction == "forward" else relation["sourceColumn"]
        table = _text((self.config["entities"].get(target_entity) or {}).get("table"), 200)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", table) or not _ID.fullmatch(key_column):
            return dict(status="blocked", relation=code, message="关系缺少合法的物理表或关联字段")
        known = {str(value) for row in source_evidence.get("rows") or [] for value in row.values()
                 if value is not None}
        keys = [str(item).strip() for item in (params.get("source_keys") or []) if str(item).strip()]
        keys = list(dict.fromkeys(keys))
        if not keys or len(keys) > 200:
            return dict(status="rejected", message="source_keys 需要 1–200 个主键")
        foreign = [key for key in keys if key not in known]
        if foreign:
            return dict(status="rejected", message="source_keys 必须来自 from_evidence 的结果，不能扩到范围外对象。",
                        outside=foreign[:5])
        attributes = self.config["attributes"].get(target_entity) or {}
        fields = [_text(item, 80) for item in (params.get("fields") or [])][:12]
        columns, unknown = [], []
        for field in fields:
            column = _text((attributes.get(field) or {}).get("column"), 80)
            if column and _ID.fullmatch(column):
                columns.append(column)
            else:
                unknown.append(field)
        if unknown or not columns:
            return dict(status="rejected", message="fields 必须是目标逻辑实体的业务属性英文名。", unknown=unknown,
                        entity=target_entity)
        if key_column not in columns:
            columns.insert(0, key_column)
        with self.lock:
            if self.queries >= self.budget["maxQueries"]:
                return dict(status="budget_exhausted", message="本范围的查询预算已用尽。")
            self.queries += 1
            used = self.queries
        try:
            database = self.database()
            schema = getattr(getattr(database, "config", None), "schema", "ded_public") or "ded_public"
            schema_name, table_name = table.split(".", 1)
            if schema != "ded_public" and _ID.fullmatch(schema):
                schema_name = schema
            select = ", ".join(f'"{column}"' for column in dict.fromkeys(columns))
            sql = (f'SELECT {select} FROM "{schema_name}"."{table_name}" '
                   f'WHERE "{key_column}"::text = ANY(%(keys)s)')
            with database.snapshot() as reader:
                result = reader.run(sql, dict(keys=keys), max_rows=2000)
        except Exception as exc:  # noqa: BLE001
            return dict(status="error", relation=code, message=f"{type(exc).__name__}：{str(exc)[:200]}",
                        budgetUsed=used)
        rows = [dict(row) for row in result.rows]
        matched = {str(row.get(key_column)) for row in rows if row.get(key_column) is not None}
        with self.lock:
            evidence_id = self.next_id("E")
            self.evidence[evidence_id] = dict(
                id=evidence_id, kind="relation", relation=code, direction=direction, entity=target_entity,
                fromEvidence=source_evidence["id"], dataAsOf=dt.datetime.now().isoformat(timespec="seconds"),
                rowCount=len(rows), truncated=bool(result.truncated), columns=list(result.columns), rows=rows,
                depth=depth)
        preview = self.budget["previewRows"]
        return dict(
            status="incomplete" if result.truncated else ("ok" if rows else "empty"),
            evidenceId=evidence_id, relation=code, name=relation["name"], direction=direction,
            entity=target_entity, cardinality=relation["cardinality"], depth=depth,
            match=dict(sourceKeys=len(keys), matchedKeys=len(matched), unmatchedKeys=len(keys) - len(matched),
                       rows=len(rows), rowsPerMatchedKey=round(len(rows) / len(matched), 2) if matched else 0),
            columns=list(result.columns), rows=rows[:preview],
            notes=["一对多关系：回到上层比较前先按事实键去重或分别聚合，不能直接相乘。"]
            if "N" in relation["cardinality"] else [],
            budgetUsed=used, budgetLeft=self.budget["maxQueries"] - used)

    # -- evaluate_and_record ---------------------------------------------
    def evaluate_and_record(self, params):
        if self.scope is None:
            return dict(status="rejected", message="先调用 G360ResolveScope 确定分析范围。")
        code = _text(params.get("code"), 40)
        kind = onto.element_kind(self.config, code)
        if kind not in {"risks", "causes"}:
            return dict(status="rejected", message="只能评估全局本体中的风险或根因编码。")
        status = _text(params.get("assessment_status"), 10)
        if status not in STATUSES:
            return dict(status="rejected", message="assessment_status 只能是：" + "、".join(STATUSES))
        support = [_text(item, 12) for item in params.get("evidence_ids") or []]
        counter = [_text(item, 12) for item in params.get("counter_evidence_ids") or []]
        missing_ids = [item for item in support + counter if item not in self.evidence]
        if missing_ids:
            return dict(status="rejected", message="引用了本次分析中不存在的证据编号。", unknown=missing_ids)
        missing_inputs = [_text(item, 120) for item in params.get("missing_inputs") or [] if _text(item, 120)]
        basis = _text(params.get("basis"), 600)
        if status in _NEED_EVIDENCE and not support:
            return dict(status="rejected", message=f"“{status}”需要同范围的必要证据：请给出 evidence_ids，否则改用待核实或无法判定。")
        if status in _NEED_EVIDENCE and any(self.evidence[item]["quality"] in {"incomplete"} for item in support
                                             if "quality" in self.evidence[item]):
            return dict(status="rejected", message="所引证据被截断，不足以判定成立或未命中；请用聚合查询或改为待核实。")
        if status == "无法判定" and not missing_inputs:
            return dict(status="rejected", message="“无法判定”必须在 missing_inputs 中写明缺少的输入、权限、配置或可比口径。")
        if status in _NEED_REASON and not basis:
            return dict(status="rejected", message=f"“{status}”需要在 basis 中写明依据。")
        item = self.config[kind][code]
        with self.lock:
            record_id = self.next_id("R")
            record = dict(
                id=record_id, kind=kind[:-1], code=code, name=item.get("name", ""),
                assessmentStatus=status, isEstablished=STATUSES[status], basis=basis,
                evidenceIds=support, counterEvidenceIds=counter, missingInputs=missing_inputs,
                rule=_text(item.get("rule"), 40), decidedBy=_text(params.get("decided_by"), 20) or "规则与证据",
                scope=dict(activity=self.scope["activity"], period=self.scope.get("period")),
                versions=self.versions(), recordedAt=dt.datetime.now().isoformat(timespec="seconds"))
            self.records = [r for r in self.records if not (r["kind"] == record["kind"] and r["code"] == code)]
            self.records.append(record)
        return dict(status="recorded", record={key: value for key, value in record.items() if key != "versions"},
                    note="未评估、不适用均不计为未命中；多根因覆盖同一对象时影响金额按事实主键去重，不能直接相加。")

    # -- draft_and_recheck -----------------------------------------------
    def draft_and_recheck(self, params):
        if self.scope is None:
            return dict(status="rejected", message="先调用 G360ResolveScope 确定分析范围。")
        wanted = [_text(item, 40) for item in params.get("cause_codes") or [] if _text(item, 40)]
        records = {r["code"]: r for r in self.records if r["kind"] == "cause"}
        if not wanted:
            wanted = [code for code, record in records.items() if record["assessmentStatus"] in {"成立", "待核实"}]
        drafts, skipped = [], []
        for code in wanted:
            cause = self.config["causes"].get(code)
            if not cause:
                skipped.append(dict(code=code, reason="全局本体中没有该根因"))
                continue
            record = records.get(code)
            status = record["assessmentStatus"] if record else "未评估"
            if status in {"未命中", "不适用"}:
                skipped.append(dict(code=code, reason=f"根因评估为{status}，不生成建议"))
                continue
            row = next((item for item in self.config["evidence"] if item["cause"] == code), {})
            confirmed = status == "成立"
            for advice_code in cause.get("advice") or []:
                advice = self.config["advice"].get(advice_code) or {}
                drafts.append(dict(
                    adviceCode=advice_code, causeCode=code, causeName=cause["name"], causeStatus=status,
                    type="改进措施" if confirmed else "核查措施",
                    name=advice.get("name", ""),
                    measure=(advice.get("content", "") if confirmed else
                             "先核查并补齐证据：" + (row.get("required") or cause.get("aiFocus") or "按根因成立规则补充取证")),
                    objects=advice.get("objects", ""), role=advice.get("role", ""),
                    deadline=advice.get("deadline", ""), acceptance=advice.get("acceptance", ""),
                    recheck=dict(metrics=row.get("recheck") or advice.get("tracking") or [],
                                 close=row.get("close", ""), baseline="复检沿用本次范围的对象、期间和口径"),
                    evidenceIds=(record or {}).get("evidenceIds", []), recordId=(record or {}).get("id", "")))
            if not cause.get("advice"):
                skipped.append(dict(code=code, reason="全局本体未登记该根因的行动建议"))
        return dict(status="drafted" if drafts else "empty", drafts=drafts, skipped=skipped,
                    note="以上是建议草稿，不是已下发的任务；任务令须由责任人确认后下发。证据不足的条目只给核查措施。")


_SCHEMAS = [
    dict(
        name="G360ResolveScope",
        description=(
            "resolve_scope：把问题解析成可执行的分析范围。每次分析的第一步，也是期间或对象变化、重开分析时的第一步。"
            "路由优先级：卡片带入的条款 → 明确编码 → 场景词和指标语义。返回流程活动（PR/BA）、已定位的风险/根因/指标、"
            "期间语义、口径、本体版本和查询预算；缺关键期间时返回 needs_period，定位不到时返回 needs_clarification。"),
        input_schema=dict(type="object", properties=dict(
            question=dict(type="string", description="用户原话，用于按场景词和指标语义找候选"),
            anchor_codes=dict(type="array", items=dict(type="string"), description="明确的风险、根因或指标编码"),
            primary_code=dict(type="string", description="本次分析的主锚点编码；缺省取第一个已定位的编码"),
            year=dict(type="string", description="统计年度 YYYY"),
            period_start=dict(type="string", description="统计开始日 YYYY-MM-DD"),
            period_end_exclusive=dict(type="string", description="统计结束日（不含）YYYY-MM-DD"),
            observed_date=dict(type="string", description="观察日 YYYY-MM-DD"),
            channel=dict(type="string", description="金额 / 电量 / 金额与电量分别判断"),
            use_handoff=dict(type="boolean", description="是否沿用卡片带入的条款；重开无关分析时传 false")))),
    dict(
        name="G360GetSubgraph",
        description=(
            "get_subgraph：按锚点装配全局本体的最小子图。风险 → 触发指标与规则 → 候选根因 → 证据要求 → 建议与复检；"
            "根因 → 规则、指标、证据、建议；指标 → 规则 → 风险。同时返回该子图可用的登记查询（含启用状态）和已验收的实体关系。"
            "节点只按本体编码连接。"),
        input_schema=dict(type="object", properties=dict(
            code=dict(type="string", description="风险、根因或指标编码；缺省为当前范围的主锚点")))),
    dict(
        name="G360ExecuteQuery",
        description=(
            "execute_query：执行一条全局本体登记的查询（T 模板 / Q 配置查询），只读。只能用 G360GetSubgraph 返回的查询索引，"
            "不接受 SQL。期间缺省沿用当前范围。MOCK、待验收查询会被阻断并返回原因。返回证据编号、列、输出绑定、行数、"
            "最多 100 行预览和结果质量（ok / empty / zero / incomplete / timeout / denied / error）。"),
        input_schema=dict(type="object", required=["query_index"], properties=dict(
            query_index=dict(type="string", description="查询索引，如 T005、Q031"),
            params=dict(type="object", description="查询参数：按筛选契约的参数名传值，列表参数传数组"),
            purpose=dict(type="string", description="这次取数要证明或反证什么")))),
    dict(
        name="G360DrillRelation",
        description=(
            "drill_relation：沿一条已验收的实体关系，从上一步证据中的主键取关联记录。source_keys 必须来自 from_evidence，"
            "fields 是目标逻辑实体的业务属性英文名（最多 12 个）。未验收的候选关系会被拒绝；最多 3 跳。返回匹配统计和证据编号。"),
        input_schema=dict(type="object", required=["relation_code", "from_evidence", "source_keys", "fields"],
                          properties=dict(
            relation_code=dict(type="string", description="关系编码，如 ER06"),
            direction=dict(type="string", enum=["forward", "reverse"], description="forward：源→目标；reverse：目标→源"),
            from_evidence=dict(type="string", description="来源证据编号"),
            source_keys=dict(type="array", items=dict(type="string"), description="来源主键，1–200 个"),
            fields=dict(type="array", items=dict(type="string"), description="要读取的业务属性英文名")))),
    dict(
        name="G360EvaluateAndRecord",
        description=(
            "evaluate_and_record：记录一条风险或根因的评估结论。状态：成立 / 未命中（同范围必要证据齐备）、"
            "待核实（有支持线索但缺关键确认）、无法判定（缺必要输入、权限、配置或可比口径，须写 missing_inputs）、"
            "不适用（证据确认不满足适用前提）、未评估（未触发、未调用或预算停止）。成立和未命中必须引用本次分析的证据编号。"),
        input_schema=dict(type="object", required=["code", "assessment_status"], properties=dict(
            code=dict(type="string", description="风险或根因编码"),
            assessment_status=dict(type="string", enum=list(STATUSES)),
            basis=dict(type="string", description="判定依据：指标值、比较基准和差距，引用证据"),
            evidence_ids=dict(type="array", items=dict(type="string"), description="支持证据编号"),
            counter_evidence_ids=dict(type="array", items=dict(type="string"), description="反证证据编号"),
            missing_inputs=dict(type="array", items=dict(type="string"), description="缺失的输入"),
            decided_by=dict(type="string", description="规则命中 / 结构性解释 / 人工确认")))),
    dict(
        name="G360DraftAndRecheck",
        description=(
            "draft_and_recheck：按已记录的根因结论生成建议草稿和复检计划。成立的根因给本体登记的行动建议（责任角色、措施、"
            "期限、验收标准、复检指标）；待核实或未评估的根因只给核查措施。草稿不下发，任务令由责任人确认。"),
        input_schema=dict(type="object", properties=dict(
            cause_codes=dict(type="array", items=dict(type="string"),
                             description="根因编码；缺省为已记录为成立或待核实的根因")))),
]


def schemas():
    return [dict(item) for item in _SCHEMAS]


def build_executors(run):
    """name → executor(params, cwd) bound to one session's Run."""
    methods = dict(G360ResolveScope=run.resolve_scope, G360GetSubgraph=run.get_subgraph,
                   G360ExecuteQuery=run.execute_query, G360DrillRelation=run.drill_relation,
                   G360EvaluateAndRecord=run.evaluate_and_record, G360DraftAndRecheck=run.draft_and_recheck)

    def bind(method):
        def execute(params, cwd=""):
            try:
                return _json(method(params or {}))
            except onto.Analysis360Unavailable as exc:
                return _json(dict(status="unavailable", message=str(exc)))
        return execute
    return {name: bind(method) for name, method in methods.items()}


def unbound_executor(params, cwd=""):
    """Registry default: the 360 tools only work inside a 360 analysis session."""
    return _json(dict(status="unavailable", message="该工具只在 360 智能分析会话中可用。"))
