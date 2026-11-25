import React, {useLayoutEffect, useRef, useState} from "react";

import MarkdownText from "../adapters/MarkdownText.jsx";
import ToolGroup from "../adapters/ToolGroup.jsx";

function Clarification({choice, onChoose, onStop}) {
  const [selected, setSelected] = useState(() => (choice.picked || []).map((item) => item.id));
  const [manual, setManual] = useState(() => (choice.picked || []).find((item) => item.id.startsWith("manual:"))?.label || "");
  const options = choice.options || [];
  const toggle = (option) => {
    const id = String(option.id ?? option.label ?? "");
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };
  const submit = (event) => {
    event.preventDefault();
    const picked = options.filter((option) => selected.includes(String(option.id ?? option.label ?? "")));
    if (manual.trim()) picked.push({id: `manual:${manual.trim()}`, label: manual.trim()});
    if (picked.length) onChoose(picked);
  };
  return (
    <form className="ak-clarify" aria-label="补充条件" onSubmit={submit}>
      <p className="ak-clarify-question">{choice.question}</p>
      {choice.context ? <MarkdownText text={choice.context} /> : null}
      {choice.error ? <p role="alert">{choice.error}</p> : null}
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
        <input aria-label="自定义补充条件" placeholder="输入其他条件" value={manual} onChange={(event) => setManual(event.target.value)} />
        <button type="submit" className="ak-primary" disabled={!selected.length && !manual.trim()}>
          {selected.length ? `确定（已选 ${selected.length} 项）` : "确定"}
        </button>
        <button type="button" className="ak-ghost" onClick={onStop}>结束本轮</button>
      </div>
    </form>
  );
}

function stageNote(turn) {
  const step = (turn.sop?.todos || []).find((item) => item.status === "in_progress");
  if (step) return step.detail || step.content || step.text || "";
  const running = (turn.assistant.tools || []).find((tool) => tool.status === "running");
  if (running) return `正在调用 ${running.name}`;
  return "";
}

function Turn({turn, error, onRetry, onOpenOntology}) {
  const {text, tools} = turn.assistant;
  const thinking = String(turn.assistant.thinking || "").trim();
  const hasAnswer = Boolean(text.trim());
  const showError = turn.status === "error";
  const active = turn.status === "streaming" || turn.status === "paused";
  const stage = active ? stageNote(turn) : "";
  return (
    <article className="ak-turn">
      {turn.user ? <div className="ak-user" tabIndex={-1} data-question-anchor={turn.id}><p>{turn.user}</p></div> : null}
      {(turn.resolvedChoices || []).map((choice, index) => (
        <p key={index} className="ak-choice-confirmed">已确认：{choice.labels.join("、")}</p>
      ))}
      {active ? (
        <div className="ak-stage" role="status" aria-live="polite">
          <span className="ak-stage-dot" aria-hidden="true" />
          <span className="ak-stage-text">{stage || "准备分析…"}</span>
          {thinking ? (
            <details className="ak-thinking">
              <summary>思考过程</summary>
              <p>{thinking}</p>
            </details>
          ) : null}
        </div>
      ) : null}
      {(turn.warnings || []).map((warning, index) => <p key={index} className="ak-progress ak-progress--warn">{warning}</p>)}
      {hasAnswer || tools.length || showError ? (
        <div className="ak-assistant">
          {hasAnswer ? <MarkdownText text={text} /> : null}
          {tools.length ? (
            <ToolGroup key={active ? "active" : "settled"} active={active}
              tools={tools} onOpenOntology={onOpenOntology} />
          ) : null}
          {showError ? (
            <div className="ak-inline-error" role="alert">
              <span>{error || "本轮分析失败"}</span>
              <button type="button" className="ak-link" onClick={onRetry}>重试本轮</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export default function Thread({turns, status, error, pendingChoice, onChoose, onStop, onRetry, onOpenOntology,
  jump, onPrefill, mode, name}) {
  const transcriptRef = useRef(null);
  const followLatest = useRef(true);
  useLayoutEffect(() => {
    const viewport = transcriptRef.current;
    if (viewport && followLatest.current) viewport.scrollTop = viewport.scrollHeight;
  }, [turns, status, pendingChoice]);
  useLayoutEffect(() => {
    if (!jump) return;
    const target = [...(transcriptRef.current?.querySelectorAll("[data-question-anchor]") || [])]
      .find((node) => node.dataset.questionAnchor === jump.id);
    if (!target) return;
    followLatest.current = false;
    target.focus({preventScroll: true});
    target.scrollIntoView?.({block: "start"});
  }, [jump]);

  const trackScroll = ({currentTarget}) => {
    followLatest.current = currentTarget.scrollHeight - currentTarget.scrollTop - currentTarget.clientHeight < 48;
  };

  if (!turns.length) {
    return (
      <div className="ak-transcript" ref={transcriptRef} onScroll={trackScroll}>
        <div className="ak-empty" role="status">
          <h2 className="ak-empty-title">{name ? `${name}，你好。 ` : ""}{mode === "report" ? "从一份报表开始" : "从一个经营问题开始"}</h2>
          <p className="ak-empty-text">
            展开工具调用可查看查询证据和本体命中。生成的明细和图表会出现在结果看板。
          </p>
          <ul className="ak-suggestions">
            {(mode === "report" ? ["概括报表中的主要变化和异常。", "按业务板块对比本期和上期的变化。"] : [
              "PACK 未签单商机主要涉及哪些客户和产品部？缺口怎么算出来的？",
              "本期商机覆盖风险最高的三个客户是谁，依据是什么？",
            ]).map((prompt) => <li key={prompt}><button type="button" className="ak-ghost"
              onClick={() => onPrefill(prompt)}>{prompt}</button></li>)}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="ak-transcript" ref={transcriptRef} onScroll={trackScroll} aria-live="polite">
      {turns.map((turn) => (
        <Turn key={turn.id} turn={turn} error={error} onRetry={onRetry} onOpenOntology={onOpenOntology} />
      ))}

      {pendingChoice ? <Clarification key={pendingChoice.toolUseId || pendingChoice.question} choice={pendingChoice}
        onChoose={onChoose} onStop={onStop} /> : null}

      {status === "interrupted" ? (
        <div className="ak-progress ak-progress--warn" role="status">
          本轮已停止，已保留当前结论与结果；可继续追问。
        </div>
      ) : null}
    </div>
  );
}
