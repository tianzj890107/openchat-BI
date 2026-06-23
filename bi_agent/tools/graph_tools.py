"""
Graph-mode retrieval tools (图库检索) — exposed to the BI agent only when
检索模式 = 图库检索.

  - GraphContext : Step 3「上下文准备」. From a 业务对象 / 指标 anchor (the LLM
        picks which, by name or code), pull the whole de-duplicated sub-tree of
        excel rows as background context.
  - GraphExpand  : 分析步骤(L3–L5)的「图库扩散探索」skill. When context is
        insufficient, diffuse from a 业务对象 anchor through 活动→流程 and
        活动上下游 to reach upstream/downstream 业务对象 and pull their rows.

Both run on the in-memory OntologyStore via GraphRetriever (always consistent
with the loaded 本体源).
"""

from __future__ import annotations

from typing import Callable

from ..ontology.retriever import GraphRetriever
from ..ontology.store import OntologyStore


Executor = Callable[[dict, str], str]
ExecutorFactory = Callable[[OntologyStore], Executor]


# ---------------------------------------------------------------------------
# GraphContext — anchor → pruned sub-tree context (Step 3)
# ---------------------------------------------------------------------------

GRAPH_CONTEXT_SCHEMA = {
    "name": "GraphContext",
    "description": (
        "图库检索 · 上下文准备(第3步)。给定一个业务对象或指标锚点,沿图库"
        "层级一次性拉取其全部下挂的本体行信息(已剪枝去重),作为回答问题的"
        "背景上下文。\n"
        "- 业务对象锚点 → 该业务对象 + 其下逻辑实体/业务属性 + 其下指标。\n"
        "- 指标锚点 → 该指标 + 可下钻维度 + 指标维度矩阵,并自动上挂其业务对象"
        "作为新锚点下钻该业务对象全部行信息。\n"
        "先用 `query` 传入用户问题里的业务名词由系统在业务对象库/指标库里匹配"
        "锚点;若已确定编码,直接用 `anchor` 传 BO/指标编码。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "业务名词/短语,用于在业务对象库与指标库中匹配锚点。",
            },
            "anchor": {
                "type": "string",
                "description": "已确定的锚点编码(业务对象 BOxxxx 或指标 Mxxxx),优先于 query。",
            },
        },
    },
}


def _make_graph_context(store: OntologyStore) -> Executor:
    retriever = GraphRetriever(store)

    def run(params: dict, cwd: str) -> str:
        anchor = (params.get("anchor") or "").strip()
        query = (params.get("query") or "").strip()
        if anchor:
            return retriever.context_bundle(anchor)
        if not query:
            return "GraphContext: 请提供 query(业务名词)或 anchor(锚点编码)。"
        cands = retriever.resolve_anchor(query)
        if not cands:
            return (f"GraphContext: 在业务对象库/指标库中未匹配到 {query!r} 的锚点。"
                    "可改用 `ListBusinessObjects` 浏览全部业务对象后再指定 anchor。")
        if len(cands) > 1:
            lines = [f"GraphContext: {query!r} 命中 {len(cands)} 个候选锚点,请用 anchor 指定其一后重试:"]
            for kind, code, name in cands[:12]:
                label = "业务对象" if kind == "business_object" else "指标"
                lines.append(f"- [{code}] {name} ({label})")
            return "\n".join(lines)
        kind, code, name = cands[0]
        return retriever.context_bundle(code, kind=kind)

    return run


# ---------------------------------------------------------------------------
# GraphExpand — diffusion exploration (L3–L5)
# ---------------------------------------------------------------------------

GRAPH_EXPAND_SCHEMA = {
    "name": "GraphExpand",
    "description": (
        "图库检索 · 扩散探索 skill(仅 L3–L5 根因/决策/执行,且已有上下文不足时使用)。"
        "从一个业务对象锚点出发,沿『活动 → 所属流程(取整条流程行信息)』与"
        "『活动上下游(活动流流转)』找到该业务对象可能对应的上下游业务对象,"
        "把它们作为新锚点并下钻其全部行信息,从而补充更多背景上下文。\n"
        "传入业务对象编码(BOxxxx);若传指标编码会自动定位其业务对象。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "anchor": {
                "type": "string",
                "description": "业务对象编码 BOxxxx(或指标编码,将自动定位其业务对象)。",
            },
        },
        "required": ["anchor"],
    },
}


def _make_graph_expand(store: OntologyStore) -> Executor:
    retriever = GraphRetriever(store)

    def run(params: dict, cwd: str) -> str:
        anchor = (params.get("anchor") or "").strip()
        if not anchor:
            return "GraphExpand: 请提供 anchor(业务对象编码)。"
        return retriever.expand(anchor)

    return run


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SPECS: list[tuple[dict, ExecutorFactory]] = [
    (GRAPH_CONTEXT_SCHEMA, _make_graph_context),
    (GRAPH_EXPAND_SCHEMA, _make_graph_expand),
]

# Tool names whitelisted for the agent only in graph retrieval mode.
GRAPH_TOOL_NAMES = [schema["name"] for schema, _ in SPECS]
