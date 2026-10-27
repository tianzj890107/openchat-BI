"""Deterministic S00 routing for Process360 questions.

The router never calls a model and never touches the database.  It maps a
question to one P01-P18 SOP, one scenario when the wording is unambiguous, and
lists the S01-S08 skills that the execution layer must run.
"""

from __future__ import annotations

import re
from typing import Iterable

from .catalog import Process360Catalog
from .models import RouteDecision


SCENARIO_KEYWORDS: dict[str, tuple[tuple[str, int], ...]] = {
    "SC05": (
        ("计划外发货", 6), ("计划外", 4), ("发货偏差", 5), ("计划对账", 5),
        ("日计划", 3), ("发货计划", 3), ("偏离计划", 4),
    ),
    "SC01": (
        ("超期未发", 6), ("订未发", 6), ("发货超期", 6), ("交付超期", 5),
        ("超期", 3), ("未发", 3), ("交期", 3), ("延期", 3), ("发货", 1),
    ),
    "SC02": (
        ("红区报价", 6), ("红区", 5), ("报价", 4), ("报价申请", 5),
        ("价格区间", 3), ("审批慢", 3),
    ),
    "SC03": (
        ("战略客户", 6), ("客户突破", 6), ("商机", 4), ("覆盖率", 4),
        ("待突破", 5), ("目标缺口", 3),
    ),
    "SC04": (
        ("中标未签", 6), ("中标", 4), ("未签", 4), ("签单", 3),
        ("合同签订", 3), ("投标", 2),
    ),
}

# (keyword regex, SOP, intent, reason).  Order is significant: the first
# matching rule wins so that "任务下发" never falls through to generic diagnosis.
SOP_RULES: tuple[tuple[str, str, str, str], ...] = (
    (r"复验|验收|能否关闭|可以关闭|整改有效|效果达标|闭环结果", "P15", "verify", "复验/关闭语义"),
    (r"下发|发待办|发到待办|发送任务令|派给|通知责任人|催办", "P12", "dispatch", "任务下发语义"),
    (r"拆(成|解成)?任务|任务令草稿|任务清单|整改计划|行动计划草稿", "P11", "draft", "任务拆解语义"),
    (r"怎么办|怎么处理|如何处置|怎么改|改善建议|对策|方案比选|优先.*(补料|排产|调整)|下一步", "P10", "recommend", "行动方案语义"),
    (r"算不出|算不出来|取不到|缺失|不一致|对不上|口径冲突|为什么没有数", "P16", "data_gap", "数据缺口/冲突语义"),
    (r"为什么|为何|原因|根因|导致|怎么会", "P09", "root_cause", "根因诊断语义"),
    (r"异常|预警|核查|哪些订单.*(超期|未发|风险)|风险.*(多少|哪些|多大)|问题.*(多少|哪些)", "P06", "anomaly", "异常预警语义"),
    (r"排名|哪个|哪些客户|集中|top\s*\d*|占比|分布|按.*(拆|看)|下钻|明细清单", "P05", "breakdown", "结构/下钻语义"),
    (r"趋势|走势|变化|环比|同比|对比|比上月|比去年", "P04", "trend", "趋势对比语义"),
    (r"预测|预计|情景|模拟|能完成多少|目标.*(差距|完成)", "P17", "forecast", "预测/情景语义"),
    (r"影响.*(多少|收入|金额|客户)|损失|敞口|会影响", "P08", "impact", "影响测算语义"),
    (r"流程|谁负责|审批|前置条件|要满足什么|节点|卡在", "P02", "process", "流程规则语义"),
    (r"经营情况|整体情况|总体.*(如何|怎么样)|主要风险|分析报告|经营概览", "P18", "overview", "综合经营语义"),
    (r"怎么算|如何计算|定义|口径|是什么|有什么区别|含义|公式", "P01", "definition", "定义口径语义"),
    (r"多少|当前|现在|本月|本周|今年|列出|清单|明细|查询", "P03", "fact", "指标问数语义"),
)

DEFAULT_RULE = (r".*", "P03", "fact", "默认指标问数")


def _score_scenarios(question: str) -> list[tuple[str, int]]:
    text = question.lower()
    scores: list[tuple[str, int]] = []
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        score = 0
        for keyword, weight in keywords:
            if keyword.lower() in text:
                score += weight
        if score:
            scores.append((scenario, score))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return scores


def _match_rule(question: str) -> tuple[str, str, str]:
    for pattern, sop, intent, reason in (*SOP_RULES, DEFAULT_RULE):
        if re.search(pattern, question, flags=re.IGNORECASE):
            return sop, intent, reason
    return DEFAULT_RULE[1], DEFAULT_RULE[2], DEFAULT_RULE[3]


def _clean_question(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def detect_scenarios(question: str) -> list[str]:
    return [scenario for scenario, _score in _score_scenarios(_clean_question(question))]


def route(question: str, catalog: Process360Catalog, *, scenario: str | None = None,
          allowed_scenarios: Iterable[str] | None = None) -> RouteDecision:
    text = _clean_question(question)
    if not text:
        raise ValueError("question is required")
    allowed = {item.strip().upper() for item in (allowed_scenarios or []) if str(item).strip()}
    known = {str(row.get("code") or "").upper() for row in catalog.records("scenarios")}
    scores = [(code, score) for code, score in _score_scenarios(text) if not known or code in known]
    if allowed:
        scores = [(code, score) for code, score in scores if code in allowed]
    explicit = str(scenario or "").strip().upper()
    if explicit:
        if catalog.scenario(explicit) is None:
            raise ValueError(f"unknown scenario: {explicit}")
        selected: str | None = explicit
        candidates: tuple[str, ...] = (explicit,)
    elif not scores:
        selected, candidates = None, ()
    elif len(scores) == 1:
        selected, candidates = scores[0][0], (scores[0][0],)
    else:
        top, second = scores[0], scores[1]
        # A clear lead (e.g. "超期未发" + "发货") selects; two unrelated
        # domains need a clarification instead of guessing.
        selected = top[0] if top[1] >= 5 and top[1] >= second[1] + 2 else None
        candidates = tuple(code for code, _score in scores[:4])

    sop_id, intent, reason = _match_rule(text)
    sop = catalog.sop(sop_id) or {}
    clarification: list[str] = []
    if selected is None and candidates:
        clarification.append(
            "问题同时涉及多个场景，请确认本次分析范围：" + "、".join(candidates)
        )
    if sop_id in {"P06", "P09", "P10", "P11", "P12", "P13", "P14", "P15"} and selected is None:
        clarification.append("请确认要治理的场景：" + "、".join(
            f"{code} {catalog.scenario(code).get('name', '')}" for code in ("SC01", "SC02", "SC03", "SC04", "SC05")
            if catalog.scenario(code)
        ))
    required = tuple(
        part.strip()
        for part in re.split(r"[；;、,，]", str(sop.get("requiredInputs") or ""))
        if part.strip()
    )
    skills = tuple(str(item) for item in sop.get("skills") or ()) or ("S01", "S02")
    return RouteDecision(
        sop_id=sop_id,
        sop_title=str(sop.get("title") or sop_id),
        scenario=selected,
        intent=intent,
        skills=skills,
        required_inputs=required,
        clarification=tuple(clarification),
        candidate_scenarios=candidates,
        reasons=(reason, f"scenario score {scores[:3]}"),
    )
