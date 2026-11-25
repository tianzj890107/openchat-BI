import React from "react";
import {presentSop} from "../../src/sopPresentation.js";

const statusLabels = {
  completed: "已完成", in_progress: "执行中", pending: "待执行", failed: "失败", cancelled: "已停止",
};

export default function SopBar({sop, status}) {
  const steps = (sop?.todos || []).map((step) => ({...step, text: step.content}));
  const {active, skipped, done, total} = presentSop(steps);
  const current = active.find((item) => item.status === "in_progress");
  const summary = status === "paused" ? "等待补充条件"
    : status === "interrupted" ? "已停止"
    : status === "error" ? "分析失败"
    : current?.text || (steps.length ? "" : status === "streaming" ? "准备中" : "待开始");
  return (
    <details className="ak-tools ak-sop" data-agentkit-sop>
      <summary>
        <strong>分析 SOP</strong>
        {total ? <span className="ak-sop-count">{done}/{total}</span> : null}
        {summary ? <span className="ak-sop-summary" role="status">{summary}</span> : null}
      </summary>
      {active.length ? (
        <ol className="ak-sop-steps">
          {active.map((step) => (
            <li key={step.text} data-status={step.status}>
              <span>{step.text}</span><small>{statusLabels[step.status] || statusLabels.pending}</small>
              {step.detail && step.detail !== step.text ? <span className="ak-sop-detail">{step.detail}</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {skipped.length ? <p>本轮无需执行：{skipped.join("、")}</p> : null}
      {!steps.length ? <p>本轮尚无流程记录。</p> : null}
    </details>
  );
}
