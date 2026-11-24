import React from "react";

function TableResult({item}) {
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
                <td key={String(column)}>{Array.isArray(row) ? String(row[cell] ?? "—") : String(row?.[column] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartResult({item}) {
  const series = item.chart?.series || [];
  const values = series.map((point) => Number(point.value) || 0);
  const max = Math.max(1, ...values.map((value) => Math.abs(value)));
  return (
    <ul className="ak-bars">
      {series.map((point, index) => (
        <li key={String(point.label ?? index)} className="ak-bar">
          <span className="ak-bar-label">{String(point.label ?? index)}</span>
          <span className="ak-bar-track">
            <span
              className="ak-bar-fill"
              style={{width: `${Math.round((Math.abs(values[index]) / max) * 100)}%`}}
            />
          </span>
          <span className="ak-bar-value">{String(point.value ?? "")}</span>
        </li>
      ))}
    </ul>
  );
}

function MetricResult({item}) {
  const metric = item.metric || {};
  return (
    <div className="ak-metric">
      <span className="ak-metric-value">{String(metric.value)}</span>
      <span className="ak-metric-unit">{metric.unit || ""}</span>
      {metric.caliber ? <p className="ak-metric-caliber">{metric.caliber}</p> : null}
    </div>
  );
}

export default function Board({items, status}) {
  return (
    <div className="ak-board-inner">
      <header className="ak-board-head">
        <h2>本轮结果</h2>
        <span className="ak-board-status">
          {status === "streaming" ? "持续更新" : items.length ? `共 ${items.length} 项` : "等待分析"}
        </span>
      </header>
      {items.length === 0 ? (
        <p className="ak-board-empty">
          结果会随本轮分析出现在这里：结论、指标口径、明细表、图表与证据。切换问题可回看当时的结果。
        </p>
      ) : (
        items.map((item) => (
          <section key={item.id} className="ak-card" data-kind={item.kind}>
            <h3 className="ak-card-title">{item.title}</h3>
            {item.kind === "table" ? <TableResult item={item} /> : null}
            {item.kind === "chart" ? <ChartResult item={item} /> : null}
            {item.kind === "metric" ? <MetricResult item={item} /> : null}
          </section>
        ))
      )}
    </div>
  );
}
