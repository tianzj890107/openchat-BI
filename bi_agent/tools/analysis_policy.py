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
    "决策建议",
    "决策与建议",
    "改进建议",
    "处置建议",
    "下一步行动",
    "行动方案",
    "建议",
)

# Section names used as boundaries when carving out an action block. A
# following 结论/根因/建议/etc. heading ends the current action section.
ALL_SECTION_NAMES = ROOT_CAUSE_SECTION_NAMES + ACTION_SECTION_NAMES + (
    "结论",
    "关键结论",
    "关键数据",
    "口径说明",
    "附图",
    "分析提醒",
    "跨维洞察",
    "问题定位",
    "方案对比",
    "行动计划",
    "监控盘",
    "复盘",
)

# Generic management platitudes are NOT concrete actions.  The regex matches
# only a short phrase that is *entirely* a platitude (e.g. 加强管理 / 持续关注 /
# 继续观察 / 强化监督), so a specific action like 加强华东客户价格管理 still passes.
_VAGUE_ACTION_RE = re.compile(
    r"^(?:建议|需|需要|要|应|应当|请|建议)?"
    r"(?:继续|持续|进一步|不断|更加)?"
    r"(?:加强|优化|完善|改善|提升|强化|深化|治理|整改|关注|重视|跟踪|监督|观察|监控|建设|管理|跟进)"
    r"(?:管理|工作|水平|力度|能力|意识|机制|建设)?[。！？!?;；、，,]*$"
)

# An item that claims an action has already been executed is not a
# recommendation and must not be presented as one.
_COMPLETED_CLAIM_RE = re.compile(
    r"^\s*(?:已|已经)(?:完成|执行|落实|处理|解决|上线|部署|整改|跟进)",
)

_ITEM_MARKER_RE = re.compile(
    r"^\s*(?:\d+[.、)]|[（(]\s*\d+\s*[）)]|[-*•·]|[一二三四五六七八九十]+[、.)])\s+",
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


def _action_section_spans(text: str) -> list[list[str]]:
    """Return every action-section block, bounded by any other heading."""
    lines = str(text or "").splitlines()
    spans: list[list[str]] = []
    start = -1
    for i, raw in enumerate(lines):
        if has_named_section(raw, ACTION_SECTION_NAMES):
            if start >= 0:
                spans.append(lines[start:i])
            start = i
        elif start >= 0 and has_named_section(raw, ALL_SECTION_NAMES):
            spans.append(lines[start:i])
            start = -1
    if start >= 0:
        spans.append(lines[start:])
    return spans


def _header_remainder(line: str) -> str | None:
    """Return content after an action heading name (``行动建议：先复核…``)."""
    for name in ACTION_SECTION_NAMES:
        head = _header_line(line).replace("**", "").strip()
        if not head.startswith(name):
            continue
        rest = head[len(name):].lstrip(r"：:—\-（(、* \t")
        return rest or None
    return None


def _is_vague_action(line: str) -> bool:
    text = _ITEM_MARKER_RE.sub("", str(line or ""))
    text = re.sub(r"[\s*>#\]\[()（）]", "", text).strip()
    text = re.sub(r"[。！？!?;；、，,]+$", "", text)
    if not text or len(text) < 4:
        return True
    return bool(_VAGUE_ACTION_RE.match(text))


def extract_action_items(text: str | None) -> list[str]:
    """Extract concrete action items from the action section of a response.

    Returns the cleaned item lines.  Vague platitudes and completed-claim
    statements are dropped; a section that is only a heading yields [].
    """
    items: list[str] = []
    seen: set[str] = set()
    for block in _action_section_spans(text):
        header_rest = _header_remainder(block[0])
        content_lines = ([header_rest] + block[1:]) if header_rest else block[1:]
        current: list[str] = []

        def flush() -> None:
            if not current:
                return
            line = re.sub(r"\s+", " ", " ".join(current)).strip()
            current.clear()
            if not line:
                return
            clean_line = _ITEM_MARKER_RE.sub("", line).strip()
            if _is_vague_action(clean_line) or _COMPLETED_CLAIM_RE.match(clean_line):
                return
            key = re.sub(r"\s+", "", line)
            if key in seen:
                return
            seen.add(key)
            items.append(line)

        for raw in content_lines:
            line = raw.strip()
            if not line:
                flush()
                continue
            if _ITEM_MARKER_RE.match(line):
                flush()
                current.append(line)
            else:
                current.append(line)
        flush()
    return items


def split_action_item(line: str) -> dict[str, str | None]:
    """Best-effort split of one action item into title/content/evidence."""
    text = re.sub(r"\s+", " ", str(line or "")).strip()
    text = _ITEM_MARKER_RE.sub("", text).strip()
    title: str | None = None
    content = text
    bold = re.match(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$", text)
    if bold and bold.group(1).strip():
        title = bold.group(1).strip()
        content = bold.group(2).strip()
    else:
        prefix = re.match(r"^([^：:，,。]{1,24})[:：]\s*(.+)$", text)
        if prefix:
            title = prefix.group(1).strip()
            content = prefix.group(2).strip()
    if not title:
        clause = re.match(r"^(.{1,20}?)[,，。;；]\s*(.+)$", text)
        if clause:
            title = clause.group(1).strip()
            content = clause.group(2).strip()
    evidence: str | None = None
    evidence_match = re.search(
        r"[（(](?:依据|证据|数据|对应根因|基于)[：:]?\s*([^）)]+)[）)]",
        content,
    )
    if not evidence_match:
        evidence_match = re.search(
            r"(?:依据|证据|数据|对应根因)[：:]?\s*([^，。；;]+)",
            content,
        )
    if evidence_match:
        evidence = evidence_match.group(1).strip()
    return {
        "title": (title or content or "")[:80],
        "content": (content or text or ""),
        "evidence": evidence,
    }


def has_effective_action(text: str | None) -> bool:
    """True when the response contains at least one concrete action item."""
    return bool(extract_action_items(text))
