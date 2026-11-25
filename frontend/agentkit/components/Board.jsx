import React, {useState} from "react";

import {chartInsightPrompt, turnBoardItems, turnSections} from "../results.js";
import MarkdownText from "../adapters/MarkdownText.jsx";
import Delivery from "./Delivery.jsx";
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
      {item.footnote ? <p className="ak-card-note">{item.footnote}</p> : null}
      {item.sourceNote ? <p className="ak-card-note">{item.sourceNote}</p> : null}
    </div>
  );
}

function MultiDimCard({item, onInsight, busy}) {
  const [activeKey, setActiveKey] = useState(item.defaultKey);
  const dimension = item.dimensions.find((dim) => dim.key === activeKey) || item.dimensions[0];
  const prompt = onInsight && chartInsightPrompt(dimension.chart.spec);
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
      {prompt ? <button type="button" className="ak-ghost" disabled={busy} onClick={() => onInsight(prompt)}>深入洞察</button> : null}
    </section>
  );
}

function ResultCard({item, onInsight, onPrefill, busy}) {
  if (item.chartType === "multi") return <MultiDimCard item={item} onInsight={onInsight} busy={busy} />;
  const prompt = onInsight && chartInsightPrompt(item.spec);
  const clauses = item.sectionKind === "rootcause"
    ? [...item.content.matchAll(/^\s*(?:[-*•]|\d+[.、)])\s+(.+)$/gm)].map((match) => match[1]) : [];
  return (
    <section className="ak-card" data-kind={item.kind}>
      <h3 className="ak-card-title">{item.title}</h3>
      {item.kind === "table" ? <TableCard item={item} /> : null}
      {item.kind === "chart" ? <ProBiChart chart={item.spec} /> : null}
      {item.kind === "text" ? <MarkdownText text={item.content} /> : null}
      {clauses.length ? <details>
        <summary>按根因追问</summary>
        {clauses.map((clause, index) => <button key={index} type="button" className="ak-ghost"
          onClick={() => onPrefill(clause)}>{clause}</button>)}
      </details> : null}
      {item.spec?.source_note ? <p className="ak-card-note">{item.spec.source_note}</p> : null}
      {prompt ? <button type="button" className="ak-ghost" disabled={busy} onClick={() => onInsight(prompt)}>深入洞察</button> : null}
    </section>
  );
}

export default function Board({turns, status, onJump, onInsight, onPrefill, busy}) {
  const groups = (turns || [])
    .map((turn, index) => ({
      turn,
      index,
      items: [...turnSections(turn).map((section) => ({...section, id: `${turn.id}:${section.kind}`,
        sectionKind: section.kind, kind: "text"})),
        ...turnBoardItems(turn)],
    }))
    .filter((group) => group.turn.user || group.items.length);
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
                  <button type="button" className="ak-link ak-turn-question" title="定位到对话"
                    aria-label={`定位到对话：${group.turn.user}`} onClick={(event) => {
                      event.preventDefault();
                      onJump(group.turn.id);
                    }}>{group.turn.user}</button>
                </summary>
                <div className="ak-turn-results-body">
                  {group.items.map((item) => (
                    <ResultCard key={item.id} item={item} onInsight={onInsight} onPrefill={onPrefill} busy={busy} />
                  ))}
                  {group.items.length === 0 && !group.turn.assistant?.text ? <p className="ak-board-empty">暂无结果</p> : null}
                  {["done", "error", "interrupted"].includes(group.turn.status) &&
                    (group.items.length || group.turn.assistant?.text?.trim()) ? <Delivery turn={group.turn}
                      index={group.index} items={group.items.some((item) => item.kind === "text") || !group.turn.assistant?.text?.trim()
                        ? group.items : [...group.items,
                        {kind: "text", title: "分析答复", content: group.turn.assistant.text},
                      ]} /> : null}
                </div>
              </details>
            );
          })
        )}
      </section>

    </div>
  );
}
