import React from "react";

function ToolGroup({tools}) {
  if (!tools.length) return null;
  return (
    <details className="ak-tools" open={tools.some((tool) => tool.status === "running")}>
      <summary>
        <span className={`ak-dot ak-dot--${tools.some((tool) => tool.status === "running") ? "live" : "done"}`} />
        工具过程 · {tools.length} 步
      </summary>
      <ol className="ak-tool-list">
        {tools.map((tool) => (
          <li key={tool.id} className="ak-tool" data-status={tool.status}>
            <span className="ak-tool-name">{tool.name}</span>
            <span className="ak-tool-state">
              {tool.status === "running" ? "执行中…" : tool.output ? "已完成" : "已调用"}
            </span>
            {tool.input ? <code className="ak-tool-input">{tool.input}</code> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

function Clarification({choice, onChoose}) {
  if (!choice) return null;
  return (
    <div className="ak-clarify" role="group" aria-label="补充条件">
      <p className="ak-clarify-question">{choice.question}</p>
      <div className="ak-clarify-options">
        {choice.options.map((option) => {
          const label = option.label ?? option.title ?? String(option.id);
          return (
            <button key={label} type="button" className="ak-option" onClick={() => onChoose(option)}>
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function Thread({turns, status, error, pendingChoice, onChoose, onRetry}) {
  if (!turns.length) {
    return (
      <div className="ak-empty" role="status">
        <h2 className="ak-empty-title">从一个经营问题开始</h2>
        <p className="ak-empty-text">
          提问后，结论、指标口径、查询证据和命中的本体关系会一起回到本页；右侧保留该轮的结果看板。
        </p>
        <ul className="ak-suggestions">
          <li>PACK 未签单商机主要涉及哪些客户和产品部？缺口怎么算出来的？</li>
          <li>本期商机覆盖风险最高的三个客户是谁，依据是什么？</li>
        </ul>
      </div>
    );
  }

  return (
    <div className="ak-transcript" aria-live="polite">
      {turns.map((turn) => (
        <article key={turn.id} className="ak-turn">
          <div className="ak-user">
            <p>{turn.user}</p>
          </div>
          <div className="ak-assistant">
            {turn.assistant.text ? (
              <div className="ak-answer">{turn.assistant.text}</div>
            ) : (
              <div className="ak-answer ak-answer--muted">
                {turn.status === "streaming" ? "正在取证…" : "本轮没有文字结论"}
              </div>
            )}
            <ToolGroup tools={turn.assistant.tools} />
            {turn.status === "error" ? (
              <div className="ak-inline-error" role="alert">
                <span>{error || "本轮分析失败"}</span>
                <button type="button" className="ak-link" onClick={onRetry}>
                  重试本轮
                </button>
              </div>
            ) : null}
          </div>
        </article>
      ))}

      {pendingChoice ? <Clarification choice={pendingChoice} onChoose={onChoose} /> : null}

      {status === "streaming" ? (
        <div className="ak-progress" role="status">
          <span className="ak-spinner" aria-hidden="true" />
          正在执行本轮分析…
        </div>
      ) : null}
      {status === "interrupted" ? (
        <div className="ak-progress ak-progress--warn" role="status">
          本轮已停止，已保留当前结论与结果；可继续追问。
        </div>
      ) : null}
    </div>
  );
}
