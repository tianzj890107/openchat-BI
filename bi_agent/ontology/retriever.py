"""
GraphRetriever — graph-mode context retrieval over an OntologyStore.

Used by the BI agent when 检索模式 = 图库检索. It implements the two
mechanical capabilities of the graph-mode SOP (the LLM still does the
semantic *matching*; this class does the deterministic *traversal*):

  - context_bundle(anchor)  — Step 3「上下文准备」: from a 业务对象 or 指标
        anchor, pull its whole sub-tree of excel rows (BO → 逻辑实体 → 业务属性,
        BO 下的指标; 指标 → 维度 + 指标维度矩阵, 并上挂其业务对象再下钻),
        pruned + de-duplicated, as background context.

  - expand(anchor)          — 分析步骤(L3–L5)的「图库扩散探索」skill:
        from an anchor 业务对象, walk its 活动 → 流程 (whole 流程 rows) and the
        活动上下游 (活动流 transitions) to reach upstream/downstream 业务对象,
        add them as new anchors and pull their sub-trees — yielding more context.

Traversal runs on the in-memory store (the graph's own source data), so it is
always consistent with the loaded 本体源 regardless of the persisted .graphml.
"""

from __future__ import annotations

from typing import Optional

from .store import OntologyStore


class GraphRetriever:
    def __init__(self, store: OntologyStore) -> None:
        self.store = store
        # Reverse adjacency the store doesn't already index.
        self._bo_activities: dict[str, list[str]] = {}      # bo -> [activity, ...]
        self._activity_processes: dict[str, list[str]] = {}  # activity -> [process, ...]
        self._metrics_by_bo: dict[str, list[str]] = {}      # bo -> [metric, ...]
        for act in store.activities.values():
            for bo in act.object_codes:
                if bo in store.business_objects:
                    self._bo_activities.setdefault(bo, []).append(act.code)
        for proc in store.processes.values():
            for ac in proc.activity_codes:
                self._activity_processes.setdefault(ac, []).append(proc.code)
        for m in store.metrics.values():
            bo = self._bo_of_metric(m.code)
            if bo:
                self._metrics_by_bo.setdefault(bo, []).append(m.code)

    # ------------------------------------------------------------------
    # Anchor resolution (the LLM supplies the phrase / code; we match codes)
    # ------------------------------------------------------------------

    def _bo_of_metric(self, metric_code: str) -> Optional[str]:
        m = self.store.metrics.get(metric_code)
        if not m or not m.bo_name:
            return None
        if m.bo_name in self.store.business_objects:
            return m.bo_name
        return self.store._bo_by_name.get(m.bo_name.lower())

    def resolve_anchor(self, query: str) -> list[tuple[str, str, str]]:
        """Match a phrase/code to (kind, code, name) anchor candidates,
        best-first. kind ∈ {business_object, indicator}. Empty if no match."""
        q = (query or "").strip()
        if not q:
            return []
        ql = q.lower()
        s = self.store
        # 1) explicit code
        if q in s.business_objects:
            bo = s.business_objects[q]
            return [("business_object", bo.code, bo.name)]
        if q in s.metrics:
            m = s.metrics[q]
            return [("indicator", m.code, m.name)]
        exact: list[tuple[str, str, str]] = []
        partial: list[tuple[str, str, str]] = []
        # 2) business objects
        for bo in s.business_objects.values():
            names = [bo.name.lower(), (bo.english or "").lower()]
            if ql in names:
                exact.append(("business_object", bo.code, bo.name))
            elif any(n and (ql in n or n in ql) for n in names):
                partial.append(("business_object", bo.code, bo.name))
        # 3) metrics (name + aliases)
        for m in s.metrics.values():
            names = [m.name.lower(), *[a.lower() for a in m.aliases]]
            if ql in names:
                exact.append(("indicator", m.code, m.name))
            elif any(n and (ql in n or n in ql) for n in names):
                partial.append(("indicator", m.code, m.name))
        return exact + partial

    # ------------------------------------------------------------------
    # Step 3 — context bundle
    # ------------------------------------------------------------------

    def _bo_subtree(self, bo_code: str, seen: set, lines: list[str]) -> None:
        s = self.store
        bo = s.business_objects.get(bo_code)
        if not bo or bo.code in seen:
            return
        seen.add(bo.code)
        lines.append(f"## 业务对象锚点 [{bo.code}] {bo.name}")
        lines.append(bo.to_prompt())
        les = s.logical_entities_of(bo.code)
        if les:
            le_codes = {le.code for le in les}
            lines.append(f"\n### 逻辑实体 ({len(les)})")
            for le in les:
                if le.code in seen:
                    continue
                seen.add(le.code)
                lines.append(le.to_prompt())
                attrs = s.attributes_of(le.code)
                if attrs:
                    lines.append(f"  属性 ({len(attrs)}):")
                    for a in attrs:
                        if a.code in seen:
                            continue
                        seen.add(a.code)
                        lines.append("    " + a.to_prompt())
                # ER 关系:仅当源、目标逻辑实体都在当前业务对象锚点下才收录;
                # 跨业务对象的 ER 关系留到根因分析阶段由 GraphExpand 扩散获取。
                for r in s.relations_of(le.code):
                    if r.code in seen:
                        continue
                    if r.source_code not in le_codes or r.target_code not in le_codes:
                        continue
                    seen.add(r.code)
                    lines.append("  关系: " + r.to_prompt().splitlines()[0])
        metrics = self._metrics_by_bo.get(bo.code, [])
        if metrics:
            lines.append(f"\n### 业务对象下指标 ({len(metrics)})")
            for mc in metrics:
                if mc in seen:
                    continue
                seen.add(mc)
                lines.append(s.metrics[mc].to_prompt())

    def _metric_subtree(self, metric_code: str, seen: set, lines: list[str]) -> None:
        s = self.store
        m = s.metrics.get(metric_code)
        if not m or m.code in seen:
            return
        seen.add(m.code)
        lines.append(f"## 指标锚点 [{m.code}] {m.name}")
        lines.append(m.to_prompt())
        # dimensions (rows) + dim matrix applicability
        dims = []
        for short in m.applicable_dimensions:
            dc = s._dim_by_shortname.get(short.lower())
            if dc and dc in s.dimensions:
                dims.append(s.dimensions[dc])
        if dims:
            lines.append(f"\n### 可下钻维度 ({len(dims)})")
            for d in dims:
                if d.code in seen:
                    continue
                seen.add(d.code)
                lines.append(d.to_prompt())
        if m.applicable_dimensions:
            lines.append("  指标维度矩阵(适用维度): " + "、".join(m.applicable_dimensions))
        # parent BO anchor → drill down
        bo = self._bo_of_metric(m.code)
        if bo:
            lines.append(f"\n### 上挂业务对象(新增锚点)→ 下钻全部行信息")
            self._bo_subtree(bo, seen, lines)

    def context_bundle(self, anchor_code: str, kind: str = "") -> str:
        """Build the pruned + de-duplicated sub-tree context for one anchor."""
        s = self.store
        seen: set = set()
        lines: list[str] = []
        if (kind == "business_object") or (not kind and anchor_code in s.business_objects):
            self._bo_subtree(anchor_code, seen, lines)
        elif (kind == "indicator") or (not kind and anchor_code in s.metrics):
            self._metric_subtree(anchor_code, seen, lines)
        else:
            return f"GraphContext: 锚点 {anchor_code!r} 不是已知的业务对象或指标编码。"
        if not lines:
            return f"GraphContext: 锚点 {anchor_code!r} 无可用上下文。"
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # L3–L5 — graph diffusion exploration
    # ------------------------------------------------------------------

    def expand(self, anchor_code: str) -> str:
        """From a 业务对象 anchor, diffuse two ways to reach related 业务对象 and
        pull their sub-trees as extra context:

          1) 活动流: 活动 → 所属流程(整条流程行) + 活动上下游(活动流流转)
                → 这些活动操作的业务对象;
          2) ER 关系: 锚点业务对象下逻辑实体的 ER 关系 → 连到的其他业务对象下
                逻辑实体(及其属性)。
        """
        s = self.store
        bo = s.business_objects.get(anchor_code)
        if not bo:
            # allow a metric anchor: hop to its BO first
            mbo = self._bo_of_metric(anchor_code)
            bo = s.business_objects.get(mbo) if mbo else None
        if not bo:
            return f"GraphExpand: 锚点 {anchor_code!r} 不是业务对象(或无法定位其业务对象)。"

        lines: list[str] = [f"# 图库扩散探索 · 锚点 [{bo.code}] {bo.name}"]
        related_bos: list[str] = []

        def _add_related(code: str) -> None:
            if code and code != bo.code and code not in related_bos:
                related_bos.append(code)

        # 1) 活动流扩散: 活动 → 流程 + 活动上下游 → 业务对象
        acts = self._bo_activities.get(bo.code, [])
        if acts:
            proc_seen: set = set()
            neighbor_acts: set = set()
            lines.append(f"\n## 业务对象下活动 ({len(acts)}) → 所属流程")
            for ac in acts:
                act = s.activities[ac]
                lines.append(f"- 活动 [{act.code}] {act.name}")
                for pc in self._activity_processes.get(ac, []):
                    if pc in proc_seen:
                        continue
                    proc_seen.add(pc)
                    proc = s.processes[pc]
                    lines.append(f"  流程 [{proc.code}] {proc.name} — 含活动 {len(proc.activity_codes)} 个:")
                    for pac in proc.activity_codes:
                        pa = s.activities.get(pac)
                        if pa:
                            lines.append(f"    · [{pa.code}] {pa.name}")
                            neighbor_acts.add(pac)
                # explicit 上下游 from flow transitions
                for nx in s._activity_flow_next.get(ac, []):
                    neighbor_acts.add(nx)
                for pv in s._activity_flow_prev.get(ac, []):
                    neighbor_acts.add(pv)
            for ac in neighbor_acts:
                act = s.activities.get(ac)
                if not act:
                    continue
                for obc in act.object_codes:
                    if obc in s.business_objects:
                        _add_related(obc)
        else:
            lines.append("\n该业务对象下未挂载活动,跳过活动流扩散。")

        # 2) ER 关系扩散: 锚点业务对象下逻辑实体 → 跨业务对象的 ER 关系 → 其他业务对象
        er_links: list[str] = []
        for le_code in s._les_by_bo.get(bo.code, []):
            for r in s.relations_of(le_code):
                other = r.target_code if r.source_code == le_code else r.source_code
                other_le = s.logical_entities.get(other)
                if not other_le or not other_le.bo_code or other_le.bo_code == bo.code:
                    continue
                _add_related(other_le.bo_code)
                obo = s.business_objects.get(other_le.bo_code)
                er_links.append(
                    f"- [{r.code}] {r.source_name or r.source_code}"
                    f" --{r.name or r.cardinality or '关联'}--> "
                    f"{r.target_name or r.target_code}"
                    f" → 业务对象 [{other_le.bo_code}] {obo.name if obo else ''}"
                )
        if er_links:
            lines.append(f"\n## ER 关系跨业务对象连接 ({len(er_links)})")
            lines.extend(er_links)

        # 3) pull each related BO's sub-tree (new anchors)
        if not related_bos:
            lines.append("\n未发现可关联的上下游业务对象。")
            return "\n".join(lines)
        lines.append(f"\n## 上下游业务对象(新增锚点 {len(related_bos)} 个)→ 下钻全部行信息")
        seen: set = {bo.code}
        for obc in related_bos:
            self._bo_subtree(obc, seen, lines)
        return "\n".join(lines)
