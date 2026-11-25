import React, {useState} from "react";

import {turnBoardItems} from "../results.js";
import ProBiChart from "./ProBiChart.jsx";

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
      <ProBiChart key={dimension.key} chart={dimension.chart.spec} />
    </section>
  );
}

function ResultCard({item}) {
  if (item.chartType === "multi") return <MultiDimCard item={item} />;
  return (
    <section className="ak-card" data-kind={item.kind}>
      <h3 className="ak-card-title">{item.title}</h3>
      {item.kind === "table" ? <TableCard item={item} /> : null}
      {item.kind === "chart" ? <ProBiChart chart={item.spec} /> : null}
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
