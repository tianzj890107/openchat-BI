import React, {useState} from "react";

import {evidenceItems, ontologyHits} from "../results.js";
import OntologyGraph from "./OntologyGraph.jsx";

function TableCard({item}) {
  const columns = item.columns?.length ? item.columns : Object.keys(item.rows?.[0] || {});
  const rows = item.rows || [];
  if (!rows.length) return <p className="ak-board-empty">该结果没有可展示的明细行。</p>;
  return (
    <div className="ak-table-wrap">
      <table className="ak-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={String(column)}>{String(column)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column, cell) => (
                <td key={String(column)}>
                  {Array.isArray(row) ? String(row[cell] ?? "—") : String(row?.[column] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {item.summary ? <p className="ak-card-note">{item.summary}</p> : null}
    </div>
  );
}

function BarChart({item}) {
  const categories = item.categories || [];
  const series = item.series?.[0];
  const values = series?.values || [];
  const max = Math.max(1, ...values.map((value) => Math.abs(value)));
  return (
    <ul className="ak-bars">
      {categories.map((label, index) => (
        <li key={label} className="ak-bar">
          <span className="ak-bar-label">{label}</span>
          <span className="ak-bar-track">
            <span
              className="ak-bar-fill"
              style={{width: `${Math.round((Math.abs(values[index] || 0) / max) * 100)}%`}}
            />
          </span>
          <span className="ak-bar-value">{String(values[index] ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function LineChart({item}) {
  const values = item.series?.[0]?.values || [];
  const max = Math.max(1, ...values.map((value) => Math.abs(value)));
  const width = 280;
  const height = 96;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values
    .map((value, index) => `${Math.round(index * step)},${Math.round(height - (Math.abs(value) / max) * height)}`)
    .join(" ");
  return (
    <svg className="ak-line" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="趋势图">
      <polyline points={points} fill="none" stroke="var(--ak-accent)" strokeWidth="2" />
    </svg>
  );
}

function PieChart({item}) {
  const slices = item.slices || [];
  const total = slices.reduce((sum, slice) => sum + Math.abs(slice.value), 0) || 1;
  let cursor = 0;
  const stops = slices.map((slice) => {
    const start = (cursor / total) * 360;
    cursor += Math.abs(slice.value);
    const end = (cursor / total) * 360;
    return `var(--ak-accent) ${start}deg ${end}deg`;
  });
  return (
    <div className="ak-pie-row">
      <div className="ak-pie" style={{background: `conic-gradient(${stops.join(", ")})`}} />
      <ul className="ak-pie-legend">
        {slices.map((slice) => (
          <li key={slice.name}>
            <span>{slice.name}</span>
            <span>{slice.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MultiDimCard({item}) {
  const [activeKey, setActiveKey] = useState(item.defaultKey);
  const dimension = item.dimensions.find((dim) => dim.key === activeKey) || item.dimensions[0];
  return (
    <section className="ak-card" data-kind="chart">
      <h3 className="ak-card-title">{item.title}</h3>
      <div className="ak-dims" role="tablist" aria-label="维度切换">
        {item.dimensions.map((dim) => (
          <button
            key={dim.key}
            type="button"
            role="tab"
            aria-selected={dim.key === dimension.key}
            className="ak-dim"
            data-active={dim.key === dimension.key ? "1" : undefined}
            onClick={() => setActiveKey(dim.key)}
          >
            {dim.label}
          </button>
        ))}
      </div>
      <p className="ak-card-note">{dimension.summary || item.summary}</p>
      <ChartBody item={dimension.chart} />
    </section>
  );
}

function ChartBody({item}) {
  if (item.chartType === "pie") return <PieChart item={item} />;
  if (item.chartType === "line") return <LineChart item={item} />;
  return <BarChart item={item} />;
}

function ResultCard({item}) {
  if (item.chartType === "multi") return <MultiDimCard item={item} />;
  return (
    <section className="ak-card" data-kind={item.kind}>
      <h3 className="ak-card-title">{item.title}</h3>
      {item.kind === "table" ? <TableCard item={item} /> : null}
      {item.kind === "chart" ? <ChartBody item={item} /> : null}
    </section>
  );
}

export default function Board({items, turns, sessionId, status}) {
  const [graphHit, setGraphHit] = useState(null);
  const evidence = evidenceItems({turns});
  const hits = ontologyHits({turns});

  return (
    <div className="ak-board-inner">
      <header className="ak-board-head">
        <h2>本轮结果</h2>
        <span className="ak-board-status">
          {status === "streaming" ? "持续更新" : items.length ? `共 ${items.length} 项` : "等待分析"}
        </span>
      </header>

      <section className="ak-board-section" data-agentkit-results>
        {items.length === 0 ? (
          <p className="ak-board-empty">
            结果会随本轮分析出现在这里：结论、指标口径、明细表、图表与证据。切换问题可回看当时的结果。
          </p>
        ) : (
          items.map((item) => <ResultCard key={item.id} item={item} />)
        )}
      </section>

      <section className="ak-board-section" data-agentkit-evidence>
        <h3 className="ak-section-title">证据 · 工具过程</h3>
        {evidence.length === 0 ? (
          <p className="ak-board-empty">本轮还没有产生可追溯的工具结果。</p>
        ) : (
          <ul className="ak-evidence">
            {evidence.map((row) => (
              <li key={row.id} className="ak-evidence-row" data-status={row.status}>
                <span className="ak-evidence-tool">{row.tool}</span>
                <span className="ak-evidence-meta">
                  {row.durationMs ? `${row.durationMs} ms` : "—"}
                  {row.hitCount ? ` · 命中 ${row.hitCount} 个本体` : ""}
                  {row.errorCode ? ` · ${row.errorCode}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ak-board-section" data-agentkit-ontology>
        <h3 className="ak-section-title">本体命中 · {hits.length}</h3>
        {hits.length === 0 ? (
          <p className="ak-board-empty">本轮还没有命中本体。分析检索到的实体会出现在这里，可打开其关联子图。</p>
        ) : (
          <ul className="ak-hits">
            {hits.map((hit) => (
              <li key={`${hit.repositoryId}:${hit.code}`}>
                <button type="button" className="ak-hit" onClick={() => setGraphHit(hit)}>
                  <span className="ak-hit-name">{hit.name}</span>
                  <span className="ak-hit-code">{hit.code}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {graphHit ? (
        <OntologyGraph hit={graphHit} sessionId={sessionId} onClose={() => setGraphHit(null)} />
      ) : null}
    </div>
  );
}
