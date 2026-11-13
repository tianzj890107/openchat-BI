"""Rule-first judgement of the 商机获取 risk card.

The ontology chain is applied in three layers, each one rule first:

1. Risks.  Every ontology risk is settled by its program rule (BR-A01~A10).
   Established risks are all shown; there is no output limit.  A risk the
   rule cannot settle (missing inputs) is sent to the model on its own, with
   its judgement rule and data.
2. Causes.  Every cause linked to an established risk is settled by its
   rule (BR-C01~C09) the same way; undecidable causes go to the model one
   at a time.
3. Advice.  An ontology advice applies when its cause is established.  This
   is fully decided by the ontology link, so advice never needs the model.

A model call that fails is reported on that item, which is then skipped;
the other items carry on.  Model answers are taken as given: there is no
second validation pass.  Every item, established or not, is listed in the
card's ontology judgement so the page shows what matched and what did not.
"""
from __future__ import annotations

import json
import os
import re
import time

KIND_LABELS = dict(risk="风险", cause="根因", advice="建议")
_LEVEL_RANK = {"极高": 0, "高": 1, "中": 2, "低": 3}

JUDGE_PROMPT = (
    "你是本体规则判定助手。程序已按规则计算，但下面这一条{kind}无法只凭结构化数据判定是否成立。"
    "请严格依据 rule 中的判定规则，结合 data 中本轮的取数结果作出判断，不得编造输入以外的数据。"
    "数据确实不足以判断时，established 返回 null，并在 reason 中写明缺少什么。"
    '只返回 JSON：{{"established": true 或 false 或 null, "level": "极高/高/中/低 或空字符串", '
    '"reason": "不超过160字的判断依据，引用 data 中的具体数值"}}，不要输出其他内容。'
)


def _text(value):
    return "" if value is None else str(value).strip()


def _established(value):
    """Read the model's verdict leniently; anything unclear is "undecided"."""
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"true", "yes", "1", "成立", "是", "命中"}:
        return True
    if text in {"false", "no", "0", "不成立", "否", "未命中"}:
        return False
    return None


def default_item_judge(request):
    """Ask the configured model about one item; raises on any call failure."""
    from ..llm import provider
    from . import opportunity_v2 as v2

    key = v2._model_candidate_keys()[0]
    messages = [dict(role="user", content=json.dumps(request, ensure_ascii=False, default=str))]
    try:
        timeout = int(os.environ.get("COCKPIT_OPPORTUNITY_JUDGE_TIMEOUT_SECONDS", "90"))
    except ValueError:
        timeout = 90
    timeout = max(15, min(timeout, 180))
    started = time.monotonic()
    label = KIND_LABELS.get(request.get("kind"), "条目")
    try:
        text, _, usage = v2._read_model_stream(
            provider, messages, JUDGE_PROMPT.format(kind=label), key,
            max_tokens=800, timeout=timeout, step=f"判定{label} {request.get('code')}")
        answer = v2._decode_model_json(text)
    except Exception as exc:  # noqa: BLE001 - annotated for the item's error
        v2._annotate_model_error(exc, key, messages, started, timeout, 800)
        raise
    return dict(answer, _model=v2._model_route_name(key), _usage=usage,
                _elapsed=round(time.monotonic() - started, 1))


def _model_error(exc):
    from .diagnostics import redact
    from .opportunity_v2 import _model_error_context, classify_model_failure

    status = dict(status="failed", error=type(exc).__name__, modelErrorMessage=str(exc)[:800],
                  **_model_error_context(exc))
    category = classify_model_failure(status)[0]
    detail = re.sub(r"\s+", " ", redact(str(exc))).strip()[:240] if str(exc) else ""
    return f"{category}" + (f"：{detail}" if detail else "")


def _ask(judge, request, progress, position):
    """One model call for one item; never raises."""
    label = KIND_LABELS.get(request["kind"], "条目")
    if progress is not None:
        progress("judging", message=f"模型判定{label} {request['code']}（{position}）")
    if judge is None:
        return dict(decidedBy="none", established=None, error="未启用模型判断，已跳过")
    try:
        answer = judge(request)
    except Exception as exc:  # noqa: BLE001 - this item is skipped, the card goes on
        return dict(decidedBy="none", established=None, error=_model_error(exc) + "，已跳过")
    if not isinstance(answer, dict):
        return dict(decidedBy="none", established=None, error="模型返回的不是 JSON 对象，已跳过")
    return dict(decidedBy="model", established=_established(answer.get("established")),
                level=_text(answer.get("level"))[:4] if _text(answer.get("level")) in _LEVEL_RANK else "",
                reason=_text(answer.get("reason"))[:400], model=_text(answer.get("_model")),
                elapsedSeconds=answer.get("_elapsed"))


def _status_label(entry):
    if entry.get("error"):
        return "判断失败，已跳过"
    if entry.get("decidedBy") == "unevaluated":
        return entry.get("reason") or "未评估"
    who = "规则" if entry.get("decidedBy") == "rule" else "模型"
    if entry.get("established") is True:
        return f"命中（{who}判定）"
    if entry.get("established") is False:
        return ("不适用（规则判定）" if entry.get("ruleStatus") == "not_applicable"
                else f"未命中（{who}判定）")
    return "无法判定（模型）"


def judge_card(evaluated, config, *, judge=None, progress=None):
    """Settle risks, causes and advice; return the card fields and the trace."""
    from .opportunity_v2 import _CAUSE_STAGE, _advice_action_type, _deadline_meta

    rules = {item.get("code"): item for item in (config.get("rules") or {}).values()} \
        if isinstance(config.get("rules"), dict) else {
            item.get("code"): item for item in config.get("rules") or []}
    risk_specs = config.get("risks") or {}
    cause_specs = config.get("causes") or {}
    advice_specs = config.get("advice") or {}
    links = config.get("links") or {}
    triggered = {risk["code"]: risk for risk in evaluated.get("risks") or []}
    candidates = {item["code"]: item for item in evaluated.get("riskCandidates") or []}
    cause_outcomes = evaluated.get("causeOutcomes") or {}
    period = _text((evaluated.get("result") or {}).get("measurementDate"))

    def rule_of(code, spec):
        rule_code = _text(spec.get("rule"))
        return dict(code=rule_code, name=_text((rules.get(rule_code) or {}).get("name")),
                    condition=_text(spec.get("condition")),
                    levelRule=_text(spec.get("levelRule")))

    # ---- risks ---------------------------------------------------------
    risk_entries = []
    pending = [code for code in risk_specs if (candidates.get(code) or {}).get("ruleStatus") == "insufficient"]
    for code, spec in risk_specs.items():
        candidate = candidates.get(code) or {}
        status = candidate.get("ruleStatus") or "insufficient"
        entry = dict(kind="risk", code=code, name=_text(spec.get("name")) or code,
                     rule=rule_of(code, spec), ruleStatus=status,
                     observed=candidate.get("observed") or [],
                     missingEvidence=candidate.get("missingEvidence") or [],
                     evidenceIds=list(candidate.get("evidenceIds") or [])[:20])
        if status == "triggered":
            risk = triggered.get(code) or {}
            entry.update(decidedBy="rule", established=True, level=risk.get("level") or "",
                         reason=_text(risk.get("description")) or "规则条件成立")
        elif status in {"not_triggered", "not_applicable"}:
            entry.update(decidedBy="rule", established=False,
                         reason="规则条件不成立" if status == "not_triggered" else "本轮没有适用对象")
        else:
            request = dict(kind="risk", code=code, name=entry["name"], period=period,
                           rule=entry["rule"], ontologyDescription=_text(spec.get("description")),
                           data=dict(observed=entry["observed"], missingInputs=entry["missingEvidence"],
                                     programNote="规则所需输入不完整，程序无法判定"))
            entry.update(_ask(judge, request, progress, f"{pending.index(code) + 1}/{len(pending)}"))
        risk_entries.append(entry)
    established_risks = {entry["code"]: entry for entry in risk_entries if entry.get("established") is True}

    # ---- causes --------------------------------------------------------
    def linked_risks(cause_code):
        codes = []
        for risk_code in established_risks:
            if cause_code in ((links.get(risk_code) or {}).get("causes") or []):
                codes.append(risk_code)
        return codes

    cause_entries = []
    cause_pending = [code for code in cause_specs
                     if linked_risks(code) and (cause_outcomes.get(code) or {}).get("ruleStatus") == "insufficient"]
    for code, spec in cause_specs.items():
        outcome = cause_outcomes.get(code) or dict(ruleStatus="insufficient", reason="缺少该根因的规则实现")
        related = linked_risks(code)
        entry = dict(kind="cause", code=code, name=_text(spec.get("name")) or code,
                     rule=rule_of(code, spec), ruleStatus=outcome.get("ruleStatus"),
                     linkedRisks=related, observed=outcome.get("observed") or [],
                     missingEvidence=outcome.get("missingEvidence") or [],
                     evidenceIds=list(outcome.get("evidenceIds") or [])[:20])
        if not related:
            entry.update(decidedBy="unevaluated", established=None,
                         reason="未评估（关联风险均未成立）")
        elif outcome.get("ruleStatus") == "triggered":
            entry.update(decidedBy="rule", established=True,
                         reason=_text(outcome.get("description")) or _text(outcome.get("reason")))
        elif outcome.get("ruleStatus") in {"not_triggered", "not_applicable"}:
            entry.update(decidedBy="rule", established=False, reason=_text(outcome.get("reason")))
        else:
            request = dict(
                kind="cause", code=code, name=entry["name"], period=period, rule=entry["rule"],
                analysisFocus=_text(spec.get("aiFocus")),
                linkedRisks=[dict(code=risk_code, name=established_risks[risk_code]["name"],
                                  judgement=established_risks[risk_code].get("reason"))
                             for risk_code in related],
                data=dict(observed=entry["observed"], missingInputs=entry["missingEvidence"],
                          programNote=_text(outcome.get("reason"))))
            entry.update(_ask(judge, request, progress, f"{cause_pending.index(code) + 1}/{len(cause_pending)}"))
        cause_entries.append(entry)
    established_causes = {entry["code"]: entry for entry in cause_entries if entry.get("established") is True}

    # ---- advice --------------------------------------------------------
    advice_entries = []
    for code, spec in advice_specs.items():
        causes = [cause for cause in spec.get("causes") or [] if cause in cause_specs]
        hit = [cause for cause in causes if cause in established_causes]
        skipped = [cause for cause in causes
                   if any(entry["code"] == cause and entry.get("error") for entry in cause_entries)]
        entry = dict(kind="advice", code=code, name=_text(spec.get("name") or spec.get("action")) or code,
                     rule=dict(code="", name="行动建议对应根因", condition="对应根因成立即采用",
                               levelRule=""),
                     linkedCauses=hit or causes, decidedBy="rule")
        if hit:
            entry.update(established=True, reason="对应根因 " + "、".join(hit) + " 已成立")
        elif skipped:
            entry.update(established=None, error="对应根因判断失败，已跳过")
        else:
            entry.update(established=False, reason="对应根因未成立")
        advice_entries.append(entry)

    # ---- card fields ---------------------------------------------------
    order = sorted(established_risks.values(),
                   key=lambda item: (_LEVEL_RANK.get(item.get("level") or "", 4), item["code"]))
    findings = [dict(
        id=f"opp-v2:risk:{entry['code']}", kind="risk_fact", title=entry["name"],
        description=entry.get("reason") or "", riskCode=entry["code"],
        riskLevel=entry.get("level") or "", decidedBy=entry["decidedBy"],
        metricCodes=[entry["code"]] + [item.get("id", "").split(":")[-1]
                                       for item in entry["observed"] if item.get("id")][:11],
        evidenceIds=entry["evidenceIds"], riskDomain="sales", riskTotalCount=len(order),
    ) for entry in order]
    finding_id = {item["riskCode"]: item["id"] for item in findings}
    causes = []
    for entry in cause_entries:
        if entry.get("established") is not True:
            continue
        evidence = entry["evidenceIds"] or [e for risk_code in entry["linkedRisks"]
                                            for e in established_risks[risk_code]["evidenceIds"][:3]]
        causes.append(dict(
            id=f"opp-v2:cause:{entry['code']}", causeCode=entry["code"],
            stage=_CAUSE_STAGE.get(entry["code"], "opportunity"), title=entry["name"],
            description=entry.get("reason") or "", decidedBy=entry["decidedBy"],
            kind="verified" if entry["decidedBy"] == "rule" else "hypothesis",
            status="supported" if entry["decidedBy"] == "rule" else "hypothesis",
            findingIds=[finding_id[code] for code in entry["linkedRisks"] if code in finding_id],
            riskCodes=list(entry["linkedRisks"]), evidenceIds=evidence[:20], missingEvidence=[],
        ))
    cause_by_code = {item["causeCode"]: item for item in causes}
    recommendations = []
    for entry in advice_entries:
        if entry.get("established") is not True:
            continue
        spec = advice_specs[entry["code"]]
        linked = [cause_by_code[code] for code in entry["linkedCauses"] if code in cause_by_code]
        days, deadline_type, deadline_text = _deadline_meta(spec.get("deadline"))
        recommendations.append(dict(
            id=f"opp-v2:advice:{entry['code']}", adviceCode=entry["code"],
            actionType=_advice_action_type(entry["code"], spec, linked),
            action=_text(spec.get("action") or spec.get("name"))[:120],
            detail=_text(spec.get("measure"))[:600], object=_text(spec.get("object"))[:200],
            ownerRole=_text(spec.get("owner")) or "待确认", deadline=deadline_text,
            deadlineType=deadline_type, deadlineDays=days,
            targetValue=_text(spec.get("target")), acceptance=_text(spec.get("acceptance")),
            tracking=_text(spec.get("tracking")), priority=_text(spec.get("priority")),
            causeIds=[cause["id"] for cause in linked],
            riskCodes=sorted({code for cause in linked for code in cause["riskCodes"]}),
            evidenceIds=list(dict.fromkeys(e for cause in linked for e in cause["evidenceIds"]))[:20],
            decidedBy="rule", ownerConfirmed=False, deadlineConfirmed=False,
        ))
    entries = risk_entries + cause_entries + advice_entries
    for entry in entries:
        entry["statusLabel"] = _status_label(entry)
    model_calls = [entry for entry in entries if entry.get("decidedBy") == "model" or entry.get("error")]
    failures = [entry for entry in entries if entry.get("error") and entry["kind"] != "advice"]
    by_rule = sum(1 for entry in order if entry["decidedBy"] == "rule")
    summary = (f"本轮 {len(risk_entries)} 项本体风险中 {len(order)} 项成立"
               f"（规则判定 {by_rule} 项，模型判定 {len(order) - by_rule} 项）"
               + (f"，成立风险涉及 {len(causes)} 项根因、{len(recommendations)} 条建议" if order else "")
               + (f"；{len(failures)} 项模型判断失败已跳过" if failures else "") + "。")
    assessments = [dict(
        code=entry["code"], name=entry["name"], rule=entry["rule"]["code"],
        condition=entry["rule"]["condition"], ruleStatus=entry["ruleStatus"],
        include=entry.get("established") is True, assessmentSource=entry.get("decidedBy"),
        classification=("confirmed" if entry.get("established") is True else
                        "not_applicable" if entry["ruleStatus"] == "not_applicable" else "insufficient"),
        description=entry.get("reason") or entry.get("error") or "",
        metricCodes=[entry["code"]], evidenceIds=entry["evidenceIds"],
        observed=entry["observed"], missingEvidence=entry["missingEvidence"],
    ) for entry in risk_entries]
    judgement = dict(
        risks=[_public(entry) for entry in risk_entries],
        causes=[_public(entry) for entry in cause_entries],
        advice=[_public(entry) for entry in advice_entries],
        modelCalls=len([entry for entry in model_calls if entry.get("decidedBy") != "unevaluated"]),
        failures=[f"{KIND_LABELS[entry['kind']]} {entry['code']}：{entry['error']}" for entry in failures],
    )
    return dict(summary=summary, findings=findings, causes=causes, analysisDimensions=[
        dict(item, id=item["id"]) for item in causes], recommendations=recommendations,
        riskAssessments=assessments, ontologyJudgement=judgement,
        riskCodes=[item["riskCode"] for item in findings],
        riskLevels={item["riskCode"]: item["riskLevel"] for item in findings},
        riskTotalCount=len(findings), includedRiskCount=len(findings))


def _public(entry):
    keep = ("kind", "code", "name", "rule", "ruleStatus", "decidedBy", "established", "level",
            "reason", "error", "statusLabel", "linkedRisks", "linkedCauses", "missingEvidence", "model")
    value = {key: entry[key] for key in keep if key in entry and entry[key] not in (None, "", [])}
    value["established"] = entry.get("established")
    return value
