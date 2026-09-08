"""Deterministic intent and section policy for deeper analysis output.

The UI must not infer a user's requested analysis depth from decorative emoji.
This module keeps the decision explainable and independent of the LLM provider:
root-cause output is enabled only for an explicit root-cause/deeper-action
request, and a root-cause section always requires a follow-up action section.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any


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
    "口径说明与限制披露",
    "限制披露",
    "冲突披露",
    "数据限制",
    "证据限制",
    "风险与限制",
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


# ---------------------------------------------------------------------------
# Lightweight structured Cognitive Policy decision record.
#
# This is an observable, deterministic routing snapshot produced once per new
# user turn.  It never calls the LLM, Doris or a remote ontology service, and
# it never stores the raw question, SQL, tool results or credentials — only a
# whitespace-normalized input digest.  ``required_tools`` describes the
# expected first-choice route and is always a subset of the session's actual
# allowed tools; it is NOT an execution whitelist.
# ---------------------------------------------------------------------------

POLICY_VERSION = 1

MODE_FACT_QUERY = "FACT_QUERY"
MODE_DIAGNOSTIC_ANALYSIS = "DIAGNOSTIC_ANALYSIS"
MODE_ONTOLOGY_LOOKUP = "ONTOLOGY_LOOKUP"
MODE_CLARIFICATION = "CLARIFICATION"
MODE_CAPABILITY_LIMITATION = "CAPABILITY_LIMITATION"
MODE_GENERAL_RESPONSE = "GENERAL_RESPONSE"

NEXT_QUERY_DORIS = "QUERY_DORIS"
NEXT_QUERY_ONTOLOGY = "QUERY_ONTOLOGY"
NEXT_ASK_USER = "ASK_USER"
NEXT_DELIVER_LIMITATION = "DELIVER_LIMITATION"
NEXT_DELIVER = "DELIVER"

# Tool names referenced by the minimal routing table.  They are plain strings
# here so the pure decision builder never depends on a live tool registry.
_TOOL_METRIC_QUERY = "Ontology-MetricQuery"
_TOOL_FACT_QUERY = "Ontology-FactQuery"
_TOOL_SEMANTIC_QUERY = "Ontology-SemanticQuery"
_TOOL_ASK_USER = "AskUser"

# Explicit term-definition / business-object / relationship lookups.  The
# "是什么" pattern deliberately does NOT match "是多少", so amount questions
# such as "采购金额是多少" remain fact queries.
_ONTOLOGY_SIGNAL_RE = re.compile(
    r"(?:定义|业务对象|本体|术语|概念|含义|数据字典|元数据|"
    r"是什么|什么是|指什么|代表什么意思|怎么理解|关系|关联)"
)

# Concrete fact / metric / list / trend signals (amounts, query verbs,
# business subjects and time dimensions).  Generic openers such as
# "帮我分析一下" carry none of these and fall through to clarification.
_FACT_SIGNAL_RE = re.compile(
    r"(?:查询|查一下|查看|统计|列出|列举|排行|排名|趋势|走势|同比|环比|"
    r"对比|明细|清单|报表|多少|金额|数量|销售额|收入|成本|利润|支出|费用|"
    r"占比|比例|规模|余额|库存|总量|合计|平均|最高|最低|最大|最小|"
    r"本月|上月|今年|去年|本季度|月份|按月|按周|按天|季度|年度|预算|"
    r"执行率|达标率|采购|订单|销售|数据|指标)"
)

# Only generic polite openers / look-around verbs: the whole (punctuation
# trimmed) question is still empty of a concrete target afterwards.
_GENERIC_ONLY_RE = re.compile(
    r"^(?:请|麻烦(?:你|您)?|帮我|给我|帮忙|我想要|我想|能不能|可以|让我)?"
    r"(?:看看|看下|看一下|随便看看|了解一下|了解下|介绍下|介绍一下|"
    r"分析一下|分析下|讲讲|说说|聊聊|讲讲看|说说看|看看情况|看看现在)*$"
)

_OUTER_PUNCT = " \t\r\n，。！？!?；;、,.:：·~～…—"


def _normalize_question(question: str | None) -> str:
    """Collapse any whitespace run and strip the ends (digest basis)."""
    return re.sub(r"\s+", " ", str(question or "")).strip()


def _input_digest(question: str | None) -> str:
    """Deterministic sha256 of the whitespace-normalized question."""
    normalized = _normalize_question(question)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_tools(allowed_tools: Any) -> list[str]:
    """Order-preserving, de-duplicated tool list (None/empty are safe)."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in allowed_tools or []:
        name = str(raw or "").strip()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _decision(
    digest: str,
    *,
    mode: str,
    reason_code: str,
    next_step: str,
    required_tools: list[str],
    evidence_required: bool,
    needs_human: bool,
) -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "mode": mode,
        "reason_code": reason_code,
        "next_step": next_step,
        "required_tools": required_tools,
        "evidence_required": evidence_required,
        "needs_human": needs_human,
        "input_digest": digest,
    }


def build_cognitive_policy_decision(
    question: str | None,
    allowed_tools: Any = None,
) -> dict[str, Any]:
    """Return the deterministic Cognitive Policy decision for one new turn.

    The decision reuses ``wants_root_cause`` / ``wants_action`` / intent
    signals already present in this module and never invokes a network
    service.  Tool availability is derived from the session's actual allowed
    tools, so ``required_tools`` can never name an unauthorized tool.  The
    raw question is never stored: only ``sha256:<hex>`` of its
    whitespace-normalized form is included.
    """

    allowed = _normalize_tools(allowed_tools)
    digest = _input_digest(question)
    normalized = _normalize_question(question)
    compact = re.sub(r"\s+", "", normalized).strip(_OUTER_PUNCT)

    has_metric = _TOOL_METRIC_QUERY in allowed
    has_fact = _TOOL_FACT_QUERY in allowed
    has_semantic = _TOOL_SEMANTIC_QUERY in allowed
    has_ask = _TOOL_ASK_USER in allowed

    def doris_route_tools() -> list[str]:
        # MetricQuery is preferred; FactQuery is the sanctioned fallback.
        # Never advertise both as required at once.
        if has_metric:
            return [_TOOL_METRIC_QUERY]
        if has_fact:
            return [_TOOL_FACT_QUERY]
        return []

    def limitation() -> dict[str, Any]:
        return _decision(
            digest,
            mode=MODE_CAPABILITY_LIMITATION,
            reason_code="QUERY_CAPABILITY_UNAVAILABLE",
            next_step=NEXT_DELIVER_LIMITATION,
            required_tools=[],
            evidence_required=False,
            needs_human=False,
        )

    # 1. Empty or purely generic questions ("帮我看看/分析一下") without a
    #    concrete object and target -> ask the user when AskUser is allowed.
    if not compact or _GENERIC_ONLY_RE.fullmatch(compact):
        if has_ask:
            return _decision(
                digest,
                mode=MODE_CLARIFICATION,
                reason_code="AMBIGUOUS_REQUEST",
                next_step=NEXT_ASK_USER,
                required_tools=[_TOOL_ASK_USER],
                evidence_required=False,
                needs_human=True,
            )
        return _decision(
            digest,
            mode=MODE_GENERAL_RESPONSE,
            reason_code="GENERAL_REQUEST",
            next_step=NEXT_DELIVER,
            required_tools=[],
            evidence_required=False,
            needs_human=False,
        )

    # 2. Diagnostic intent has priority over a plain fact query.  The single
    #    source of this classification is ``classify_intent`` (which itself
    #    reuses ``wants_root_cause`` / ``wants_action`` / _PROBLEM_INTENT_RE):
    #    L2 covers anomaly / problem / fluctuation / deviation / change,
    #    L3 root-cause analysis, L4/L5 recommendation / decision / action.
    #    No second anomaly keyword list is maintained here.
    intent = classify_intent(normalized)
    if intent.level == "L2" or intent.wants_root_cause or intent.wants_action:
        required = doris_route_tools()
        if not required:
            return limitation()
        return _decision(
            digest,
            mode=MODE_DIAGNOSTIC_ANALYSIS,
            reason_code="DIAGNOSTIC_REQUEST",
            next_step=NEXT_QUERY_DORIS,
            required_tools=required,
            evidence_required=True,
            needs_human=False,
        )

    # 3. Term-definition / business-object / relationship lookup.
    if _ONTOLOGY_SIGNAL_RE.search(compact):
        if has_semantic:
            return _decision(
                digest,
                mode=MODE_ONTOLOGY_LOOKUP,
                reason_code="ONTOLOGY_LOOKUP_REQUEST",
                next_step=NEXT_QUERY_ONTOLOGY,
                required_tools=[_TOOL_SEMANTIC_QUERY],
                evidence_required=True,
                needs_human=False,
            )
        return limitation()

    # 4. Explicit fact / metric / list / trend query.
    if _FACT_SIGNAL_RE.search(compact):
        required = doris_route_tools()
        if not required:
            return limitation()
        return _decision(
            digest,
            mode=MODE_FACT_QUERY,
            reason_code="FACT_REQUEST_RESOLVED",
            next_step=NEXT_QUERY_DORIS,
            required_tools=required,
            evidence_required=True,
            needs_human=False,
        )

    # 5. Unrecognized / general chat: answer directly, never report a Doris
    #    or ontology data need that does not exist.
    return _decision(
        digest,
        mode=MODE_GENERAL_RESPONSE,
        reason_code="GENERAL_REQUEST",
        next_step=NEXT_DELIVER,
        required_tools=[],
        evidence_required=False,
        needs_human=False,
    )


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
