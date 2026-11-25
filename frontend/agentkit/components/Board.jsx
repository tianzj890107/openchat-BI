import React, {useState} from "react";

import {turnBoardItems} from "../results.js";

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
  const present = values.filter((value) => typeof value === "number");
  const max = Math.max(1, ...present.map((value) => Math.abs(value)));
  return (
    <ul className="ak-bars">
      {categories.map((label, index) => {
        const value = values[index];
        const missing = typeof value !== "number";
        return (
          <li key={label} className="ak-bar" data-missing={missing ? "1" : undefined}>
            <span className="ak-bar-label">{label}</span>
            <span className="ak-bar-track">
              <span
                className="ak-bar-fill"
                style={{width: missing ? "0%" : `${Math.round((Math.abs(value) / max) * 100)}%`}}
              />
            </span>
            <span className="ak-bar-value">{missing ? "—" : String(value)}</span>
          </li>
        );
      })}
    </ul>
  );
}

function LineChart({item}) {
  const values = item.series?.[0]?.values || [];
  const present = values.filter((value) => typeof value === "number");
  if (!present.length) return <p className="ak-board-empty">该图没有有效数值。</p>;
  const max = Math.max(1, ...present.map((value) => Math.abs(value)));
  const width = 280;
  const height = 96;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values
    .map((value, index) => (typeof value === "number"
      ? `${Math.round(index * step)},${Math.round(height - (Math.abs(value) / max) * height)}`
      : null))
    .filter(Boolean)
    .join(" ");
  return (
    <svg className="ak-line" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="趋势图">
      <polyline points={points} fill="none" stroke="var(--ak-accent)" strokeWidth="2" />
    </svg>
  );
}

function PieChart({item}) {
  const slices = item.slices || [];
  const total = slices.reduce(
    (sum, slice) => sum + (typeof slice.value === "number" ? Math.abs(slice.value) : 0),
    0,
  ) || 1;
  let cursor = 0;
  const stops = slices
    .filter((slice) => typeof slice.value === "number")
    .map(() => "");
  let index = 0;
  for (const slice of slices) {
    if (typeof slice.value !== "number") continue;
    const start = (cursor / total) * 360;
    cursor += Math.abs(slice.value);
    const end = (cursor / total) * 360;
    stops[index] = `var(--ak-accent) ${start}deg ${end}deg`;
    index += 1;
  }
  return (
    <div className="ak-pie-row">
      <div className="ak-pie" style={{background: `conic-gradient(${stops.join(", ")})`}} />
      <ul className="ak-pie-legend">
        {slices.map((slice) => (
          <li key={slice.name}>
            <span>{slice.name}</span>
            <span>{typeof slice.value === "number" ? slice.value : "—"}</span>
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

export default function Board({turns, status}) {
  const groups = (turns || [])
    .map((turn, index) => ({
      turn,
      index,
      items: turnBoardItems(turn),
    }))
    .filter((group) => group.items.length);
  const totalItems = groups.reduce((sum, group) => sum + group.items.length, 0);

  return (
    <div className="ak-board-inner">
      <header className="ak-board-head">
        <h2>分析结果 · 按轮</h2>
        <span className="ak-board-status">
          {status === "streaming" ? "持续更新" : groups.length ? `${groups.length} 轮 · ${totalItems} 项` : "等待分析"}
        </span>
      </header>

      <section className="ak-board-section" data-agentkit-results>
        {groups.length === 0 ? (
          <p className="ak-board-empty">
            分析生成的表格和图表会按问题显示在这里。
          </p>
        ) : (
          groups.map((group, position) => {
            const isLatest = position === groups.length - 1;
            return (
              <details key={group.turn.id} className="ak-turn-results" open={isLatest}>
                <summary className="ak-turn-results-head">
                  <span className="ak-turn-index">第 {group.index + 1} 轮</span>
                  <span className="ak-turn-question">{group.turn.user}</span>
                </summary>
                <div className="ak-turn-results-body">
                  {group.items.map((item) => (
                    <ResultCard key={item.id} item={item} />
                  ))}
                </div>
              </details>
            );
          })
        )}
      </section>

    </div>
  );
}
