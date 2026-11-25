// Result adapters for the AgentKit workbench right pane.
//
// The analysis backend attaches results to the `tool_result` event itself:
//   table         {title, columns:[{key,label}], rows:[[...]], summary, ...}
//   chart         {title, chart_type, option:<echarts option>}
//   multi_chart   [chart spec, ...]
//   ontology_entities [{code, kind, name, repository_id, display}]
// These pure functions turn that wire shape into cards, evidence rows and
// subgraph requests so the UI never re-implements extraction (spec §4.2).

const ONTOLOGY_CODE_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export function tableModel(spec) {
  if (!spec || !Array.isArray(spec.columns) || !Array.isArray(spec.rows)) return null;
  return {
    id: spec.id || "",
    kind: "table",
    title: spec.title || "明细表",
    columns: spec.columns.map((column) => column?.label ?? column?.key ?? String(column)),
    rows: spec.rows,
    summary: spec.summary || "",
    footnote: spec.footnote || "",
    sourceNote: spec.source_note || "",
  };
}

// Missing values stay missing: rendering them as 0 invents data.
function numericOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function seriesFromOption(option) {
  return Array.isArray(option?.series) ? option.series : [];
}

function categoriesFromOption(option) {
  const axis = Array.isArray(option?.xAxis) ? option.xAxis[0] : option?.xAxis;
  return Array.isArray(axis?.data) ? axis.data : [];
}

export function chartModel(spec) {
  const option = spec?.option;
  if (!option || typeof option !== "object") return null;
  const chartType = spec.chart_type || "bar";
  const series = seriesFromOption(option);
  if (chartType === "pie") {
    const slices = (series[0]?.data || []).filter((point) => point && typeof point === "object");
    return {
      id: spec.id || "",
      kind: "chart",
      chartType,
      title: spec.title || "图表",
      slices: slices.map((point) => ({
        name: String(point.name ?? ""),
        value: numericOrNull(point.value),
      })),
    };
  }
  return {
    id: spec.id || "",
    kind: "chart",
    chartType,
    title: spec.title || "图表",
    categories: categoriesFromOption(option).map((value) => String(value)),
    series: series.map((entry) => ({
      name: String(entry?.name ?? ""),
      values: (Array.isArray(entry?.data) ? entry.data : []).map((value) => numericOrNull(value)),
    })),
  };
}

/**
 * Multi-dimensional drill-down (ChartGenerateMultiDim): one card keeps every
 * dimension, each with its own ECharts option, plus the default dimension.
 */
export function multiDimModel(spec) {
  if (!spec || !Array.isArray(spec.dimensions)) return null;
  const dimensions = spec.dimensions
    .map((dim) => {
      const chart = chartModel({title: dim.label || dim.key, chart_type: dim.chart_type, option: dim.option});
      if (!chart) return null;
      return {key: dim.key, label: dim.label || dim.key, summary: dim.summary || "", chart};
    })
    .filter(Boolean);
  if (!dimensions.length) return null;
  const preferred = dimensions.find((dim) => dim.key === spec.default_dim);
  return {
    kind: "chart",
    chartType: "multi",
    title: spec.title || "维度洞察",
    summary: spec.summary || "",
    dimensions,
    defaultKey: (preferred || dimensions[0]).key,
  };
}

/** One tool call may return a table, a chart, or several charts. */
export function toolBoardItems(tool) {
  const items = [];
  const table = tableModel(tool?.table);
  if (table) items.push({...table, id: `${tool.id}:table`, toolId: tool.id});
  const chart = chartModel(tool?.chart);
  if (chart) items.push({...chart, id: `${tool.id}:chart`, toolId: tool.id});
  const multi = multiDimModel(tool?.multiChart);
  if (multi) items.push({...multi, id: `${tool.id}:multi`, toolId: tool.id});
  // Legacy shape kept for streams that nest results inside `output`.
  const nested = tool?.output || {};
  if (!table && nested.table) {
    const fallback = tableModel(nested.table);
    if (fallback) items.push({...fallback, id: `${tool.id}:output-table`, toolId: tool.id});
  }
  if (!chart && nested.chart && !Array.isArray(tool?.multiChart)) {
    const fallback = chartModel(nested.chart);
    if (fallback) items.push({...fallback, id: `${tool.id}:output-chart`, toolId: tool.id});
  }
  return items;
}

/** Flatten one turn's tool calls into board cards (stable ids, no duplicates). */
export function turnsBoardItems(turns) {
  const items = [];
  const seen = new Set();
  for (const turn of turns || []) {
    for (const tool of turn.assistant?.tools || []) {
      for (const item of toolBoardItems(tool)) {
        if (seen.has(item.id)) continue;
        seen.add(item.id);
        items.push(item);
      }
    }
  }
  return items;
}

/** One turn's cards, keeping results attached to the question that produced them. */
export function turnBoardItems(turn) {
  return turnsBoardItems(turn ? [turn] : []);
}

/** One turn's evidence rows. */
export function turnEvidence(turn) {
  return evidenceItems({turns: turn ? [turn] : []});
}

/** One turn's ontology hits. */
export function turnHits(turn) {
  return ontologyHits({turns: turn ? [turn] : []});
}

/** Deduped ontology hits; the same code in two repositories stays two hits. */
export function ontologyHits(state) {
  const hits = [];
  const seen = new Set();
  for (const turn of state?.turns || []) {
    for (const tool of turn.assistant?.tools || []) {
      for (const entity of tool.entities || []) {
        const code = String(entity?.code || "").trim();
        if (!code) continue;
        const repositoryId = String(entity.repository_id || entity.repositoryId || "");
        const key = `${repositoryId}\u0000${code}`;
        if (seen.has(key)) continue;
        seen.add(key);
        hits.push({
          code,
          kind: entity.kind || entity.type || "ontology",
          name: entity.name || entity.display || code,
          display: entity.display || "",
          repositoryId,
          library: repositoryId,
          toolId: tool.id,
          turnId: turn.id,
        });
      }
    }
  }
  return hits;
}

/** One evidence row per tool call, so the board can explain where values came from. */
export function evidenceItems(state) {
  const rows = [];
  for (const turn of state?.turns || []) {
    for (const tool of turn.assistant?.tools || []) {
      if (tool.status !== "done" && !tool.errorCode) continue;
      rows.push({
        id: `${turn.id}:${tool.id}`,
        turnId: turn.id,
        toolId: tool.id,
        tool: tool.name,
        durationMs: Number(tool.durationMs) || 0,
        hitCount: (tool.entities || []).length,
        status: tool.errorCode ? "error" : "ok",
        errorCode: tool.errorCode || "",
      });
    }
  }
  return rows;
}

/** Subgraph request for one hit; invalid codes never reach the API. */
export function subgraphRequest(hit, sessionId) {
  const code = String(hit?.code || "").trim();
  if (!ONTOLOGY_CODE_RE.test(code)) return null;
  const request = {
    code,
    type: hit.kind || hit.type || "ontology",
    strategy: "context",
    session_id: sessionId || "",
  };
  const repositoryId = String(hit.repositoryId || hit.repository_id || "");
  if (repositoryId) request.repository_id = repositoryId;
  return request;
}
