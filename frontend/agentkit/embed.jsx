import React, {useCallback, useEffect, useRef, useState} from "react";
import {AssistantRuntimeProvider, AuiIf, ComposerPrimitive} from "@assistant-ui/react";

import {readEventStream, requestJson, withBasePath} from "./api.js";
import {
  applyEvent, createWorkbenchState, resumeTurn, startTurn, stopTurn,
} from "./state.js";
import Board from "./components/Board.jsx";
import SopBar from "./components/SopBar.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";
import {
  initialView, isReady, readHostView, readSnapshot, rememberSession, removeSnapshot,
  requestMessage, resumeSession, viewMessage, writeSnapshot,
} from "./embedBridge.js";

const HISTORY_KEY = "chuxiaoce.assistant.history";
const HISTORY_LIMIT = 8;

function makeSessionId() {
  const stamp = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `a360-${stamp}`;
}

function readHistory() {
  try {
    const raw = globalThis.localStorage?.getItem(HISTORY_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((item) => item && item.id) : [];
  } catch {
    return [];
  }
}

function writeHistory(list) {
  try {
    globalThis.localStorage?.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)));
  } catch { /* restricted storage */ }
}

function titleOf(turns) {
  const first = (turns || []).find((turn) => turn.user)?.user || "新的分析";
  return first.length > 32 ? `${first.slice(0, 32)}…` : first;
}

function restoreWorkbench(sessionId) {
  const snapshot = readSnapshot(sessionId);
  if (!snapshot || !Array.isArray(snapshot.turns) || !snapshot.turns.length) return createWorkbenchState();
  return {
    ...createWorkbenchState(),
    sessionId,
    turns: snapshot.turns,
    status: snapshot.pendingChoice ? "paused" : "idle",
    pendingChoice: snapshot.pendingChoice || null,
  };
}

/** 储小策嵌入式助手：360 SSE + AgentKit 组件，宿主持有 chat/board 视图。 */
export default function EmbedApp() {
  const [hostView, setHostView] = useState(() => initialView(window.location.search));
  const [boot] = useState(() => {
    const id = resumeSession(sessionStorage, makeSessionId);
    return {id, workbench: restoreWorkbench(id)};
  });
  const [sessionId, setSessionId] = useState(boot.id);
  const [workbench, setWorkbench] = useState(boot.workbench);
  const [history, setHistory] = useState(readHistory);
  const [jump, setJump] = useState(null);
  const [modelLabel, setModelLabel] = useState("");
  const controllerRef = useRef(null);
  const stateRef = useRef(workbench);
  stateRef.current = workbench;
  const busy = workbench.status === "streaming";

  useEffect(() => {
    rememberSession(sessionStorage, sessionId);
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    requestJson("api/meta").then(
      (meta) => { if (!cancelled) setModelLabel(String(meta?.agent?.model || "")); },
      () => {},
    );
    return () => { cancelled = true; };
  }, []);

  // Keep the current turn and a pending clarification across a refresh; only
  // terminal/paused states are written so a reload never resurrects a stub.
  useEffect(() => {
    if (workbench.status === "streaming") return;
    if (!workbench.turns.length && !workbench.pendingChoice) return;
    writeSnapshot(sessionId, {
      turns: workbench.turns,
      pendingChoice: workbench.pendingChoice || null,
    });
  }, [sessionId, workbench]);

  // The host sends chat/board; the child requests home/board/close. Every
  // message is checked for origin, window and the shared envelope.
  useEffect(() => {
    const origin = window.location.origin;
    const send = (payload) => window.parent?.postMessage(payload, origin);
    send({source: "cockpit-assistant", type: "ready"});
    const onMessage = (event) => {
      const view = readHostView(event, origin, window.parent);
      if (view) setHostView(view);
      else if (isReady(event, origin, window.parent)) send(viewMessage(hostView));
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [hostView]);

  const postRequest = useCallback((request) => {
    window.parent?.postMessage(requestMessage(request), window.location.origin);
  }, []);

  const persist = useCallback((id, turns) => {
    const title = titleOf(turns);
    setHistory((previous) => {
      const next = [
        {id, title, updated: new Date().toISOString(), turns},
        ...previous.filter((item) => item.id !== id),
      ];
      writeHistory(next);
      return next;
    });
    // The server copy lets another browser/process reopen the same 360 record.
    fetch(withBasePath("api/analysis360/history"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({session_id: id, title, turns}),
    }).catch(() => {});
  }, []);

  useEffect(() => {
    let cancelled = false;
    requestJson("api/analysis360/history").then((data) => {
      if (cancelled || !Array.isArray(data?.conversations)) return;
      setHistory((previous) => {
        const merged = [...previous];
        for (const item of data.conversations) {
          const existing = merged.find((entry) => entry.id === item.id);
          if (existing) existing.title = existing.title || item.title;
          else merged.push({id: item.id, title: item.title, updated: item.updated, turns: []});
        }
        writeHistory(merged);
        return merged;
      });
    }, () => {});
    return () => { cancelled = true; };
  }, []);

  const runStream = useCallback(async (opener, {choice = false} = {}) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    const fail = (message) => setWorkbench((previous) => applyEvent(previous,
      choice ? {type: "choice_failed", message} : {type: "error", message}));
    try {
      await opener(controller.signal, (event) => {
        if (controllerRef.current !== controller && event.type !== "error") return;
        if (choice && event.type === "error") {
          fail(event.message || "补充条件提交失败，请重试。");
          return;
        }
        setWorkbench((previous) => applyEvent(previous, event));
      });
    } catch (error) {
      if (error?.name !== "AbortError") fail(error.message);
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
      if (!controller.signal.aborted) persist(sessionId, stateRef.current.turns);
    }
  }, [persist, sessionId]);

  const ask = useCallback(async (text, signal, onEvent) => {
    const response = await fetch(withBasePath("api/analysis360/chat"), {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text, session_id: sessionId, analysis360_direct: true}),
      signal,
    });
    await readEventStream(response, onEvent);
  }, [sessionId]);

  const send = useCallback((text) => {
    const value = String(text || "").trim();
    if (!value || controllerRef.current || stateRef.current.status === "paused") return;
    setWorkbench((previous) => startTurn(previous, {text: value, sessionId}));
    runStream((signal, onEvent) => ask(value, signal, onEvent));
  }, [ask, runStream, sessionId]);

  const choose = useCallback((picked) => {
    const chosen = Array.isArray(picked) ? picked : picked ? [picked] : [];
    if (!chosen.length || controllerRef.current) return;
    const ids = chosen.map((item) => String(item.id ?? item.label ?? ""));
    const labels = chosen.map((item) => String(item.label ?? item.id ?? ""));
    setWorkbench((previous) => resumeTurn(previous, chosen.map((_, index) => ({id: ids[index], label: labels[index]}))));
    runStream(async (signal, onEvent) => {
      const response = await fetch(withBasePath("api/analysis360/choice"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, choice_ids: ids, choice_labels: labels}),
        signal,
      });
      await readEventStream(response, onEvent);
    }, {choice: true});
  }, [runStream, sessionId]);

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setWorkbench((previous) => stopTurn(previous));
  }, []);

  const runtime = useAgentkitRuntime({
    turns: workbench.turns,
    running: busy,
    paused: Boolean(workbench.pendingChoice),
    onNew: send,
    onCancel: stop,
  });

  const openSession = (entry) => {
    if (entry.id === sessionId) return;
    persist(sessionId, stateRef.current.turns);
    setSessionId(entry.id);
    const local = restoreWorkbench(entry.id);
    setWorkbench(local);
    setJump(null);
    if (!local.turns.length) {
      requestJson(`api/analysis360/history/${encodeURIComponent(entry.id)}`).then((record) => {
        if (record && Array.isArray(record.turns) && record.turns.length) {
          setWorkbench({...createWorkbenchState(), sessionId: entry.id, turns: record.turns});
        }
      }, () => {});
    }
  };
  const newSession = () => {
    if (controllerRef.current) return;
    persist(sessionId, stateRef.current.turns);
    const next = makeSessionId();
    setSessionId(next);
    rememberSession(sessionStorage, next);
    removeSnapshot(sessionId);
    setWorkbench(createWorkbenchState());
    setJump(null);
  };

  const welcome = (
    <>
      <h2 className="ak-empty-title">储小策，我帮你</h2>
      <p className="ak-empty-text">看目标 · 看差距 · 看趋势</p>
      <ul className="ak-suggestions">
        {["本期商机覆盖风险最高的三个客户是谁，依据是什么？",
          "PACK 未签单商机主要涉及哪些客户和产品部？缺口怎么算出来的？"].map((prompt) => (
          <li key={prompt}>
            <button type="button" className="ak-ghost" onClick={() => send(prompt)}>{prompt}</button>
          </li>
        ))}
      </ul>
    </>
  );

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="ak-embed" data-view={hostView} data-agentkit-embed="1" data-session={sessionId}>
        <aside className="ak-embed-sessions" aria-label="储小策会话">
          <div className="ak-embed-sessions-head">
            <strong>储小策智能助手</strong>
            <button type="button" className="ak-ghost" onClick={newSession} aria-label="新建对话">新对话</button>
          </div>
          <ol className="ak-embed-session-list">
            {history.length ? history.map((item) => (
              <li key={item.id}>
                <button type="button" className="ak-embed-session" data-active={item.id === sessionId ? "1" : undefined}
                  onClick={() => openSession(item)} title={item.title}>
                  {item.title}
                </button>
              </li>
            )) : <li className="ak-embed-empty">还没有历史分析，先提出一个经营问题。</li>}
          </ol>
        </aside>

        <section className="ak-embed-main">
          <header className="ak-embed-head">
            <span className="ak-embed-title">{hostView === "board" ? "对话看板" : "储小策智能助手"}</span>
            {hostView === "board" ? (
              <button type="button" className="ak-ghost" onClick={() => postRequest("home")}>返回主页</button>
            ) : (
              <button type="button" className="ak-ghost" onClick={() => postRequest("board")}>显示对话看板</button>
            )}
            <button type="button" className="ak-ghost" aria-label="收起助手" onClick={() => postRequest("close")}>收起</button>
          </header>

          <div className="ak-embed-body">
            <div className="ak-embed-chat">
              <SopBar key={`sop:${sessionId}`} sop={workbench.turns.at(-1)?.sop} status={workbench.status} />
              <Thread turns={workbench.turns} status={workbench.status} error={workbench.error}
                pendingChoice={workbench.pendingChoice} onChoose={choose} onStop={stop}
                onRetry={() => { const last = workbench.turns.at(-1)?.user; if (last) send(last); }}
                jump={jump} onPrefill={(prompt) => runtime.thread.composer.setText(prompt)}
                mode="data" name="储小策" welcome={welcome} />
              <div className="ak-composer-dock">
                <ComposerPrimitive.Root className="ak-composer">
                  <div className="ak-composer-entry">
                    <ComposerPrimitive.Input className="ak-composer-input" rows={2}
                      placeholder="描述你的经营问题，例如：本期商机覆盖风险最高的三个客户是谁？" aria-label="输入问题" />
                  </div>
                  <div className="ak-composer-actions">
                    <span className="ak-model-select" title={modelLabel || "团队模型"} aria-label={`当前模型：${modelLabel || "团队模型"}`}>
                      {String(modelLabel || "团队模型").split(" · ")[0]}
                    </span>
                    <AuiIf condition={(state) => state.thread.isRunning}>
                      <ComposerPrimitive.Cancel className="ak-stop">停止</ComposerPrimitive.Cancel>
                    </AuiIf>
                    <AuiIf condition={(state) => !state.thread.isRunning}>
                      <ComposerPrimitive.Send className="ak-send">发送</ComposerPrimitive.Send>
                    </AuiIf>
                  </div>
                </ComposerPrimitive.Root>
                {workbench.status === "error" && workbench.error ? (
                  <p className="ak-embed-error" role="alert">{workbench.error}</p>
                ) : null}
              </div>
            </div>
            {hostView === "board" ? (
              <div className="ak-embed-board" aria-label="当前对话看板">
                <Board turns={workbench.turns} status={workbench.status} busy={busy}
                  onJump={(id) => { setHostView("chat"); setJump({id}); }}
                  onPrefill={(prompt) => runtime.thread.composer.setText(prompt)}
                  onInsight={null} />
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </AssistantRuntimeProvider>
  );
}
