"""Read-only access to the 流程360全局本体 config: routing and subgraph assembly."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parent / "assets" / "global-ontology.json"
VERSION = "analysis360-global-1"


class Analysis360Unavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_config():
    try:
        config = json.loads(ASSET.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Analysis360Unavailable(f"360 智能分析的全局本体配置不可用：{type(exc).__name__}") from exc
    if config.get("version") != VERSION:
        raise Analysis360Unavailable("360 智能分析的全局本体配置版本不匹配，请重新生成")
    return config


def _text(value):
    return "" if value is None else str(value).strip()


def element_kind(config, code):
    """Which ontology sheet a code belongs to, or ""."""
    code = _text(code)
    for kind in ("risks", "causes", "metrics", "advice", "activities", "rules", "queries", "relations"):
        if code in (config.get(kind) or {}):
            return kind
    return ""


def _norm(text):
    return re.sub(r"[\s·（）()／/、，,。:：\-—]+", "", _text(text)).lower()


def match_by_name(config, text, kinds=("risks", "causes", "metrics")):
    """Candidates whose name appears in ``text`` (or the reverse).

    Text similarity only finds candidates; the caller still has to confirm
    one of them, it never connects ontology nodes by itself.
    """
    wanted = _norm(text)
    found = []
    if len(wanted) < 2:
        return found
    for kind in kinds:
        for code, item in (config.get(kind) or {}).items():
            name = _norm(item.get("name"))
            if len(name) >= 2 and (name in wanted or wanted in name):
                found.append(dict(kind=kind, code=code, name=item.get("name")))
    return found


def activity_of(config, kind, code):
    if kind == "risks":
        return _text((config["risks"].get(code) or {}).get("activity"))
    if kind == "causes":
        for risk in (config["causes"].get(code) or {}).get("risks") or []:
            activity = _text((config["risks"].get(risk) or {}).get("activity"))
            if activity:
                return activity
        return ""
    if kind == "metrics":
        for risk in (config["metrics"].get(code) or {}).get("risks") or []:
            activity = _text((config["risks"].get(risk) or {}).get("activity"))
            if activity:
                return activity
        node = _text((config["metrics"].get(code) or {}).get("node"))
        for activity in config["activities"].values():
            if activity["processName"] and activity["processName"] in node:
                return activity["code"]
    return ""


def queries_for_metrics(config, metric_codes):
    """Registered queries that output one of the metrics, enabled ones first."""
    wanted = set(metric_codes)
    found = []
    for index, query in (config.get("queries") or {}).items():
        outputs = {item["code"] for item in query.get("outputs") or [] if item.get("role") == "指标输出"}
        outputs |= set(query.get("metrics") or [])
        if outputs & wanted:
            found.append(index)
    order = {"enabled": 0, "mock": 1, "pending": 2, "isolated": 3}
    return sorted(found, key=lambda index: (order.get(config["queries"][index]["gate"], 9), index))


def query_card(config, index):
    """What the agent may know about a query before calling it (no SQL text)."""
    query = config["queries"][index]
    outputs = query.get("outputs") or []
    return dict(
        index=index, key=query["key"], mode=query["mode"], gate=query["gate"],
        gateReason=query.get("gateReason") or "", status=query.get("status") or "",
        metrics=query.get("metrics") or [], returnedDimensions=[
            dict(code=item["code"], label=item["label"]) for item in outputs if item.get("role") == "返回维度"],
        filterOnly=[item["code"] for item in outputs if item.get("role") == "仅筛选"][:20],
        parameters=sorted({name for spec in (query.get("contract") or {}).values()
                           for name in (spec.get("param"), spec.get("from"), spec.get("to")) if name}),
        note=_text(query.get("note"))[:240], sha256=query["sha256"])


def subgraph(config, kind, code):
    """The definition-layer subgraph around one anchor.

    risk  → trigger metrics and rule → candidate causes → evidence → advice / recheck
    cause → its rule and metrics, the risks it explains, evidence, advice
    metric → the rules and risks it triggers
    Nodes are connected by the workbook's codes only.
    """
    risks, causes, metrics, rules = config["risks"], config["causes"], config["metrics"], config["rules"]

    def metric_card(metric_code):
        item = metrics.get(metric_code) or {}
        return dict(code=metric_code, name=item.get("name", ""), unit=item.get("unit", ""),
                    definition=_text(item.get("definition"))[:300], rule=_text(item.get("rule"))[:240],
                    status=item.get("status", ""), queries=queries_for_metrics(config, [metric_code])[:6])

    def rule_card(rule_code):
        item = rules.get(_text(rule_code)) or {}
        return {key: _text(item.get(key)) for key in ("code", "name", "description", "trigger", "result")
                if _text(item.get(key))}

    def evidence_rows(risk_code=None, cause_code=None):
        return [row for row in config["evidence"]
                if (risk_code is None or row["risk"] == risk_code)
                and (cause_code is None or row["cause"] == cause_code)]

    def cause_card(cause_code, risk_code=None):
        item = causes.get(cause_code) or {}
        rows = evidence_rows(risk_code, cause_code) or evidence_rows(None, cause_code)
        row = rows[0] if rows else {}
        return dict(
            code=cause_code, name=item.get("name", ""), method=item.get("method", ""),
            rule=rule_card(item.get("rule")), condition=_text(item.get("condition")),
            analysisFocus=_text(item.get("aiFocus")), indicators=[metric_card(m) for m in item.get("indicators") or []],
            evidence=dict(required=row.get("required", ""), confirm=row.get("confirm", ""),
                          grain=row.get("grain", ""), queries=row.get("queries", []), gate=row.get("gate", "")),
            recheck=dict(metrics=row.get("recheck", []), close=row.get("close", "")),
            advice=[advice_card(a) for a in item.get("advice") or []])

    def advice_card(advice_code):
        item = config["advice"].get(advice_code) or {}
        return dict(code=advice_code, name=item.get("name", ""), content=item.get("content", ""),
                    role=item.get("role", ""), deadline=item.get("deadline", ""),
                    acceptance=item.get("acceptance", ""), tracking=item.get("tracking", []))

    if kind == "risks":
        risk = risks[code]
        activity = config["activities"].get(risk["activity"]) or {}
        linked = [link["cause"] for link in config["links"] if link["risk"] == code and link["cause"]]
        candidate = list(dict.fromkeys(linked or risk.get("causes") or []))
        return dict(
            anchor=dict(kind="risk", code=code, name=risk["name"], description=risk["description"],
                        condition=risk["condition"], levelRule=risk["levelRule"], objects=risk["objects"]),
            activity=dict(code=activity.get("code", ""), name=activity.get("name", ""),
                          process=activity.get("process", ""), boundary=activity.get("boundary", ""),
                          evidenceRule=activity.get("evidenceRule", "")),
            rule=rule_card(risk.get("rule")),
            indicators=[metric_card(m) for m in risk.get("indicators") or []],
            candidateCauses=[cause_card(c, code) for c in candidate if c in causes])
    if kind == "causes":
        cause = causes[code]
        return dict(
            anchor=dict(kind="cause", code=code, name=cause["name"]),
            cause=cause_card(code),
            explains=[dict(code=r, name=risks[r]["name"], activity=risks[r]["activity"])
                      for r in cause.get("risks") or [] if r in risks])
    if kind == "metrics":
        metric = metrics[code]
        triggered = [r for r in metric.get("risks") or [] if r in risks]
        return dict(
            anchor=dict(kind="metric", **metric_card(code)),
            rules=[rule_card(risks[r].get("rule")) for r in triggered],
            risks=[dict(code=r, name=risks[r]["name"], condition=risks[r]["condition"],
                        activity=risks[r]["activity"]) for r in triggered])
    raise Analysis360Unavailable(f"不支持的子图锚点类型：{kind}")


def allowed_queries(config, kind, code):
    """Queries a scope may execute: those of the anchor's subgraph."""
    metric_codes, listed = set(), set()
    if kind == "risks":
        risk = config["risks"][code]
        metric_codes |= set(risk.get("indicators") or [])
        for row in config["evidence"]:
            if row["risk"] == code:
                listed |= set(row["queries"])
                metric_codes |= set(row["recheck"])
        for cause_code in risk.get("causes") or []:
            metric_codes |= set((config["causes"].get(cause_code) or {}).get("indicators") or [])
    elif kind == "causes":
        cause = config["causes"][code]
        metric_codes |= set(cause.get("indicators") or [])
        for row in config["evidence"]:
            if row["cause"] == code:
                listed |= set(row["queries"])
                metric_codes |= set(row["recheck"])
        for risk_code in cause.get("risks") or []:
            metric_codes |= set((config["risks"].get(risk_code) or {}).get("indicators") or [])
    elif kind == "metrics":
        metric_codes.add(code)
    listed |= set(queries_for_metrics(config, metric_codes))
    return sorted(index for index in listed if index in config["queries"])
