"""Model summaries of exactly the items a stage-risk card displays.

The 【风险】【原因】【建议】 sections of the 销售额口径明细 cards each open with
a short summary.  That summary is written by the model from the few items the
section actually shows, after the card's analysis is settled.  It adds no
fact: every number must already appear in the items of the same section.

The step is best effort.  A section whose summary cannot be validated is left
without one; the card itself is never failed or altered here.
"""
from __future__ import annotations

import json
import os
import re
import time

# The card renders every risk, analysis dimension and recommendation it is
# given, so every displayed item is summarised.
DISPLAY_LIMITS = dict(risks=None, causes=None, advice=None)
SUMMARY_LIMIT = 160
SECTION_FIELDS = dict(risks="riskSummary", causes="causeSummary", advice="adviceSummary")
SECTION_LABELS = dict(risks="风险", causes="原因", advice="建议")

SUMMARY_IDENTITY = "你是经营分析卡片的摘要助手。"
SUMMARY_TASK = (
    "为卡片三段写总结。输入的 risks、causes、advice 是卡片上已经显示的条目。"
    "请分别为这三组各写一段总结：riskSummary 只总结 risks，causeSummary 只总结 causes，"
    "adviceSummary 只总结 advice。只能依据对应那一组条目的内容归纳，不得新增事实、对象、原因或措施；"
    "数字只能原样引用同一组条目里出现的数字，不得计算、合并或引用其他组的数字；"
    f"每段不超过 {SUMMARY_LIMIT - 40} 字，写成一段连贯的话，不要分点、不要 Markdown、不要出现编码。"
    "某一组没有条目时，对应字段返回空字符串。"
    "如果输入带有 validationFeedback，说明上一次的总结没有通过校验，请按 issues 修正后重新输出全部三个字段。"
    '只返回 JSON：{"riskSummary":"","causeSummary":"","adviceSummary":""}，不要输出其他内容。'
)
SYSTEM_PROMPT = SUMMARY_IDENTITY + SUMMARY_TASK


def summary_system_prompt(role=""):
    """A card with its own system role puts it first; others keep the default."""
    role = _clean(role, 2000) if role else ""
    return f"{role}\n\n本次任务：{SUMMARY_TASK}" if role else SYSTEM_PROMPT


def _clean(value, limit=400):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def displayed_items(result):
    """The text of the items each card section shows, and nothing else."""
    result = result if isinstance(result, dict) else {}
    risks = [dict(title=_clean(item.get("title"), 80), description=_clean(item.get("description")))
             for item in (result.get("findings") or [])[:DISPLAY_LIMITS["risks"]]
             if isinstance(item, dict) and (item.get("title") or item.get("description"))]
    causes = [dict(title=_clean(item.get("title"), 80), description=_clean(item.get("description")))
              for item in (result.get("analysisDimensions") or [])[:DISPLAY_LIMITS["causes"]]
              if isinstance(item, dict) and (item.get("title") or item.get("description"))]
    advice = [{key: value for key, value in dict(
                  action=_clean(item.get("action"), 160), ownerRole=_clean(item.get("ownerRole"), 40),
                  deadline=_clean(item.get("deadline") or (
                      f"{item['deadlineDays']} 个工作日" if item.get("deadlineDays") else ""), 40),
                  acceptance=_clean(item.get("acceptance"), 200)).items() if value}
              for item in (result.get("recommendations") or [])[:DISPLAY_LIMITS["advice"]]
              if isinstance(item, dict) and item.get("action")]
    return dict(risks=risks, causes=causes, advice=advice)


def validate_summaries(answer, items):
    """Keep the summaries that only restate their own section; report the rest."""
    from .opportunity_v2 import _allowed_model_numbers, _model_numbers

    summaries, issues = {}, []
    answer = answer if isinstance(answer, dict) else {}
    for section, field in SECTION_FIELDS.items():
        text = _clean(answer.get(field), 2000)
        if not items[section]:
            summaries[field] = ""
            continue
        problem = ""
        if not text:
            problem = "缺少总结"
        elif len(text) > SUMMARY_LIMIT:
            problem = f"超过 {SUMMARY_LIMIT} 字（实际 {len(text)} 字）"
        else:
            extra = sorted(_model_numbers(text) - _allowed_model_numbers(items[section]))
            if extra:
                problem = f"含本组条目中不存在的数字 {'、'.join(extra[:5])}"
        if problem:
            issues.append(f"{SECTION_LABELS[section]}总结（{field}）：{problem}")
            summaries[field] = ""
        else:
            summaries[field] = text
    return summaries, issues


def _call_model(payload, *, timeout, max_tokens, system=SYSTEM_PROMPT):
    from ..llm import provider
    from ..llm.runtime_config import request_config
    from .opportunity_v2 import _decode_model_json, _model_candidate_keys, _model_route_name

    key = _model_candidate_keys()[0]
    messages = [dict(role="user", content=json.dumps(payload, ensure_ascii=False))]
    events = []
    from ..llm.context_budget import cockpit_context_limit
    with request_config(thinking=False, request_timeout=timeout,
                        context_limit=cockpit_context_limit(), min_output_tokens=min(max_tokens, 600)):
        # An empty allowlist: this step never offers the model any tool.
        for event in provider.stream_message(messages, system, [], key,
                                             max_tokens=max_tokens, temperature=0, thinking=False):
            events.append(event)
    errors = [event.get("error", "") for event in events if event.get("type") == "error"]
    if errors:
        raise RuntimeError(str(errors[-1]))
    text = "".join(event.get("text", "") for event in events
                   if event.get("type") == "text_delta").strip()
    if not text:
        raise RuntimeError("模型未返回总结正文")
    return _decode_model_json(text), _model_route_name(key)


def summarize_sections(result, *, stage_name="", call_model=None, timeout=60, max_tokens=1500,
                       role=""):
    """Return the card's ``sectionSummaries`` or ``None`` when nothing is shown.

    One repair round is allowed: sections that failed validation are named to
    the model once.  Whatever still fails is delivered without a summary.
    """
    items = displayed_items(result)
    if not any(items.values()):
        return None
    system = summary_system_prompt(role)
    call = call_model or (lambda payload: _call_model(payload, timeout=timeout,
                                                      max_tokens=max_tokens, system=system))
    payload = dict(stage=_clean(stage_name, 40), **items)
    started = time.monotonic()
    summaries = {field: "" for field in SECTION_FIELDS.values()}
    issues, model, calls = [], "", 0
    try:
        for attempt in range(2):
            answer = call(payload)
            calls += 1
            if isinstance(answer, tuple):
                answer, model = answer
            summaries, issues = validate_summaries(answer, items)
            if not issues:
                break
            payload = dict(payload, validationFeedback=dict(
                issues=issues,
                previousAnswer={field: _clean((answer or {}).get(field), 400)
                                for field in SECTION_FIELDS.values()}
                if isinstance(answer, dict) else {}))
    except Exception as exc:  # noqa: BLE001 - the card is delivered without summaries
        from .diagnostics import redact
        issues = [f"总结调用失败：{type(exc).__name__}：{_clean(redact(str(exc)), 300)}"]
    wanted = [field for section, field in SECTION_FIELDS.items() if items[section]]
    done = [field for field in wanted if summaries.get(field)]
    return dict(
        **summaries,
        status="completed" if len(done) == len(wanted) else "partial" if done else "failed",
        issues=issues[:6], model=model, modelCalls=calls,
        basis={section: len(items[section]) for section in SECTION_FIELDS},
        durationSeconds=round(time.monotonic() - started, 1), generatedAt=time.time(),
    )


def enabled():
    return os.getenv("COCKPIT_SECTION_SUMMARY_ENABLED", "1").strip().lower() not in {
        "0", "false", "no", "off"}


def with_section_summaries(item, *, stage_name="", progress=None, summarizer=summarize_sections,
                           role=""):
    """Return ``item`` with ``result.sectionSummaries`` set; never raises."""
    if not enabled() or not isinstance(item, dict) or not isinstance(item.get("result"), dict):
        return item
    try:
        if progress is not None:
            progress("summarising", message="模型总结显示的风险、原因与建议")
        summaries = (summarizer(item["result"], stage_name=stage_name, role=role) if role
                     else summarizer(item["result"], stage_name=stage_name))
    except Exception:  # noqa: BLE001 - summaries never fail a delivered card
        return item
    if not summaries:
        return item
    return dict(item, result=dict(item["result"], sectionSummaries=summaries))
