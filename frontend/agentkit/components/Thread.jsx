import React, {useLayoutEffect, useRef, useState} from "react";

import MarkdownText from "../adapters/MarkdownText.jsx";
import ToolGroup from "../adapters/ToolGroup.jsx";

function Clarification({choice, onChoose}) {
  const [selected, setSelected] = useState([]);
  if (!choice) return null;
  const options = choice.options || [];
  const toggle = (option) => {
    const id = String(option.id ?? option.label ?? "");
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };
  const submit = () => {
    const picked = options.filter((option) => selected.includes(String(option.id ?? option.label ?? "")));
    if (picked.length) onChoose(picked);
  };
  return (
    <div className="ak-clarify" role="group" aria-label="补充条件">
      <p className="ak-clarify-question">{choice.question}</p>
      <ul className="ak-clarify-options">
        {options.map((option) => {
          const id = String(option.id ?? option.label ?? "");
          const label = option.label ?? option.title ?? id;
          return (
            <li key={id}>
              <label className="ak-option">
                <input
                  type="checkbox"
                  checked={selected.includes(id)}
                  onChange={() => toggle(option)}
                />
                <span className="ak-option-label">{label}</span>
                {option.detail ? <span className="ak-option-detail">{option.detail}</span> : null}
              </label>
            </li>
          );
        })}
      </ul>
      <div className="ak-clarify-actions">
        <button type="button" className="ak-primary" onClick={submit} disabled={!selected.length}>
          确定（已选 {selected.length} 项）
        </button>
      </div>
    </div>
  );
}

export default function Thread({turns, status, error, pendingChoice, onChoose, onRetry, onOpenOntology}) {
  const transcriptRef = useRef(null);
  const followLatest = useRef(true);
  useLayoutEffect(() => {
    const viewport = transcriptRef.current;
    if (viewport && followLatest.current) viewport.scrollTop = viewport.scrollHeight;
  }, [turns, status, pendingChoice]);

  const trackScroll = ({currentTarget}) => {
    followLatest.current = currentTarget.scrollHeight - currentTarget.scrollTop - currentTarget.clientHeight < 48;
  };

  if (!turns.length) {
    return (
      <div className="ak-transcript" ref={transcriptRef} onScroll={trackScroll}>
        <div className="ak-empty" role="status">
          <h2 className="ak-empty-title">从一个经营问题开始</h2>
          <p className="ak-empty-text">
            展开工具调用可查看查询证据和本体命中。生成的明细和图表会出现在结果看板。
          </p>
          <ul className="ak-suggestions">
            <li>PACK 未签单商机主要涉及哪些客户和产品部？缺口怎么算出来的？</li>
            <li>本期商机覆盖风险最高的三个客户是谁，依据是什么？</li>
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="ak-transcript" ref={transcriptRef} onScroll={trackScroll} aria-live="polite">
      {turns.map((turn) => (
        <article key={turn.id} className="ak-turn">
          <div className="ak-user">
            <p>{turn.user}</p>
          </div>
          <div className="ak-assistant">
            {turn.assistant.text ? (
              <MarkdownText text={turn.assistant.text} />
            ) : (
              <div className="ak-answer ak-answer--muted">
                {turn.status === "streaming" ? "正在取证…" : "本轮没有文字结论"}
              </div>
            )}
            {turn.assistant.tools.length ? (
              <ToolGroup tools={turn.assistant.tools} onOpenOntology={onOpenOntology} />
            ) : null}
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
