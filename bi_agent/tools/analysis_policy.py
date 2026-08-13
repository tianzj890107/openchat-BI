"""Deterministic intent and section policy for deeper analysis output.

The UI must not infer a user's requested analysis depth from decorative emoji.
This module keeps the decision explainable and independent of the LLM provider:
root-cause output is enabled only for an explicit root-cause/deeper-action
request, and a root-cause section always requires a follow-up action section.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


# These helpers are deliberately separate.  A user can ask for a decision
# (L4) without asking why, and a root-cause request (L3) must still carry a
# suggestion even when the user did not explicitly ask for one.
_ROOT_CAUSE_INTENT_RE = re.compile(
    r"(?:根因|根因证据链|原因|为什么|为何|怎么回事|成因|归因|导致|"
    r"深挖|深度分析|原因链)",
    re.IGNORECASE,
)
_ACTION_INTENT_RE = re.compile(
    r"(?:怎么办|如何改善|如何解决|给(?:我|出)?[^。！？\n]{0,12}方案|方案|"
    r"行动建议|管理建议|建议|措施|落地|治理|优化|决策|推荐|选哪个|该不该|"
    r"执行计划|行动计划|排期|责任人|责任视角|时间节点|完成标准|监控|复盘|跟踪|监督)",
    re.IGNORECASE,
)
_PROBLEM_INTENT_RE = re.compile(
    r"(?:有没有问题|哪里异常|异常|波动|偏差|问题|风险|对比|差距|"
    r"下滑|上涨|下降|变化)",
    re.IGNORECASE,
)
_L5_INTENT_RE = re.compile(
    r"(?:怎么落地|如何落地|落地计划|执行计划|行动计划|排期|责任人|责任视角|"
    r"时间节点|完成标准|监控指标|监控|复盘|跟踪|监督)",
    re.IGNORECASE,
)
_ROOT_NEGATION_RE = re.compile(
    r"(?:不要|无需|不需要|不用|别|不分析|不展开|仅需|只看|只查|只列).{0,16}"
    r"(?:根因|原因|为什么|为何|成因|归因|深挖|深度分析|原因链)",
    re.IGNORECASE,
)
_ACTION_NEGATION_RE = re.compile(
    r"(?:不要|无需|不需要|不用|别|不提供|不输出|不想要).{0,16}"
    r"(?:建议|方案|行动|措施|执行计划|行动计划|落地|监控|复盘)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AnalysisIntent:
    """Independent intent flags plus the highest requested delivery level."""

    level: str
    wants_root_cause: bool
    wants_action: bool

ROOT_CAUSE_SECTION_NAMES = (
    "根因分析",
    "根因证据链",
    "根因",
)
ACTION_SECTION_NAMES = (
    "行动建议",
    "管理建议",
    "建议雏形",
    "执行建议",
    "建议",
)


def wants_root_cause(question: str | None) -> bool:
    """Return whether the user explicitly asks for root-cause analysis."""

    text = re.sub(r"\s+", "", str(question or "")).strip()
    if not text or _ROOT_NEGATION_RE.search(text):
        return False
    return bool(_ROOT_CAUSE_INTENT_RE.search(text))


def wants_action(question: str | None) -> bool:
    """Return whether the user explicitly asks for a recommendation/action."""

    text = re.sub(r"\s+", "", str(question or "")).strip()
    if not text or _ACTION_NEGATION_RE.search(text):
        return False
    return bool(_ACTION_INTENT_RE.search(text))


def classify_intent(question: str | None) -> AnalysisIntent:
    """Classify the requested delivery level without merging root/action intent.

    The Agent remains the semantic authority.  This deterministic classifier is
    a small, explainable fallback for tests and UI policy; it does not replace
    the six-step SOP or ask the model to follow keywords blindly.
    """

    text = re.sub(r"\s+", "", str(question or "")).strip()
    root = wants_root_cause(text)
    action = wants_action(text)
    if not text:
        return AnalysisIntent("L1", False, False)
    if action and _L5_INTENT_RE.search(text):
        level = "L5"
    elif action:
        level = "L4"
    elif root:
        level = "L3"
    elif _PROBLEM_INTENT_RE.search(text):
        level = "L2"
    else:
        level = "L1"
    return AnalysisIntent(level, root, action)


def _header_line(line: str) -> str:
    value = str(line or "").strip()
    value = re.sub(r"^[#>*\-\s]+", "", value)
    value = re.sub(r"^\d+[.)、]\s*", "", value)
    value = re.sub(r"^\*+\s*", "", value)
    # Keep compatibility with older responses while making the section name,
    # rather than the emoji, the semantic anchor.
    value = re.sub(r"^[📌📊📎🧭📈📉📄🧩🧠✅⚠️🔍🔎💡🧮🗂️📟🔁]+\s*", "", value)
    return value.strip()


def has_named_section(text: str | None, names: tuple[str, ...]) -> bool:
    """Return true only for a line that looks like a section heading."""

    if not text:
        return False
    for raw in str(text).splitlines():
        line = _header_line(raw).replace("**", "").strip()
        for name in names:
            if not line.startswith(name):
                continue
            rest = line[len(name):]
            if rest == "" or re.match(r"^[：:—\-（(、*\s]", rest):
                return True
    return False


def has_root_cause_section(text: str | None) -> bool:
    return has_named_section(text, ROOT_CAUSE_SECTION_NAMES)


def has_action_section(text: str | None) -> bool:
    return has_named_section(text, ACTION_SECTION_NAMES)
