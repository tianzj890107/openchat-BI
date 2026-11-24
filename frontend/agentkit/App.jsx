import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AssistantRuntimeProvider} from "@assistant-ui/react";

import {chooseOption, listConversations, openConversation, streamChat} from "./api.js";
import {
  applyEvent,
  boardItems,
  createWorkbenchState,
  parseHandoff,
  startTurn,
  stopTurn,
} from "./state.js";
import Board from "./components/Board.jsx";
import Composer from "./components/Composer.jsx";
import HandoffBanner from "./components/HandoffBanner.jsx";
import SessionList from "./components/SessionList.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";

function newSessionId(handoff) {
  const stamp = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return handoff?.handoffId ? `agentkit-${handoff.handoffId}-${stamp}` : `agentkit-${stamp}`;
}

/** Rebuild display turns from a stored conversation (read-only restore). */
function hydrateTurns(messages) {
  const turns = [];
  for (const message of messages || []) {
    const blocks = Array.isArray(message.content)
      ? message.content
      : [{type: "text", text: String(message.content ?? "")}];
    const text = blocks
      .filter((block) => block && block.type === "text")
      .map((block) => block.text || "")
      .join("\n")
      .trim();
    const tools = blocks
      .filter((block) => block && block.type === "tool_use")
      .map((block) => ({
        id: block.id || block.tool_use_id || `history-tool-${turns.length}`,
        name: block.name || "tool",
        status: "done",
        input: JSON.stringify(block.input ?? {}),
        output: null,
      }));
    if (message.role === "assistant") {
      const last = turns[turns.length - 1];
      if (last) last.assistant = {text, thinking: "", tools};
    } else if (text) {
      turns.push({
        id: `history-${turns.length}`,
        user: text,
        status: "done",
        assistant: {text: "", thinking: "", tools: []},
      });
    }
  }
  return turns;
}

export default function App() {
  const handoff = useMemo(() => parseHandoff(window.location.search), []);
  const [handoffVisible, setHandoffVisible] = useState(handoff.active);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [view, setView] = useState("split");
  const [workbench, setWorkbench] = useState(() => createWorkbenchState());
  const [sessionId, setSessionId] = useState(() => newSessionId(handoff));
  const [notice, setNotice] = useState("");
  const controllerRef = useRef(null);
  const stateRef = useRef(workbench);
  stateRef.current = workbench;

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations());
    } catch (error) {
      setNotice(`会话列表加载失败：${error.message}`);
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  const runStream = useCallback(async (session, opener) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    const onEvent = (event) => setWorkbench((previous) => applyEvent(previous, event));
    try {
      await opener({sessionId: session, signal: controller.signal, onEvent});
    } catch (error) {
      if (error?.name !== "AbortError") {
        setWorkbench((previous) => applyEvent(previous, {type: "error", message: error.message}));
      }
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, []);

  const send = useCallback(
    (text) => {
      const value = String(text || "").trim();
      if (!value || stateRef.current.status === "streaming") return;
      setNotice("");
      setWorkbench((previous) => startTurn(previous, {text: value, sessionId}));
      runStream(sessionId, (options) => streamChat({...options, message: value}));
    },
    [runStream, sessionId],
  );

  const choose = useCallback(
    (picked) => {
      const pending = stateRef.current.pendingChoice;
      const chosen = Array.isArray(picked) ? picked : picked ? [picked] : [];
      if (!pending || !chosen.length) return;
      // AskUser supports multi-select: keep the ids/labels order the user picked.
      const ids = chosen.map((option) => String(option.id ?? option.label ?? ""));
      const labels = chosen.map((option) => String(option.label ?? option.id ?? ""));
      setWorkbench((previous) => ({...previous, pendingChoice: null, status: "streaming"}));
      runStream(sessionId, (options) => chooseOption({...options, ids, labels}));
    },
    [runStream, sessionId],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setWorkbench((previous) => stopTurn(previous));
  }, []);

  const startNew = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    const next = newSessionId(handoff);
    setSessionId(next);
    setActiveConversation("");
    setWorkbench(createWorkbenchState());
    setNotice("");
  }, [handoff]);

  const selectConversation = useCallback(async (cid) => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    try {
      const restored = await openConversation(cid);
      const nextSession = restored.sessionId || cid;
      setSessionId(nextSession);
      setActiveConversation(cid);
      setWorkbench({
        ...createWorkbenchState(),
        sessionId: nextSession,
        turns: hydrateTurns(restored.messages),
      });
      setNotice("");
    } catch (error) {
      setNotice(`打开会话失败：${error.message}`);
    }
  }, []);

  const restartWithoutHandoff = useCallback(() => {
    const url = new URL(window.location.href);
    for (const key of ["handoff", "anchor", "risk", "period", "filters", "evidence", "source"]) {
      url.searchParams.delete(key);
    }
    window.location.assign(url.toString());
  }, []);

  const goBackToSource = useCallback(() => {
    if (window.history.length > 1) window.history.back();
    else restartWithoutHandoff();
  }, [restartWithoutHandoff]);

  const items = boardItems(workbench);
  const runtime = useAgentkitRuntime({
    turns: workbench.turns,
    running: workbench.status === "streaming",
    onNew: send,
    onCancel: stop,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
    <div className="ak-shell" data-agentkit-root="1" data-ak-view={view}>
      <header className="ak-topbar">
        <div className="ak-brand">
          <span className="ak-brand-mark" aria-hidden="true" />
          <span className="ak-brand-name">本体消费展示工作台</span>
          <span className="ak-brand-chip">AgentKit</span>
        </div>
        <div className="ak-topbar-actions">
          <button
            type="button"
            className="ak-ghost"
            data-agentkit-layout-toggle
            onClick={() => setView((current) => (current === "board" ? "thread" : "board"))}
          >
            {view === "board" ? "看对话" : "看结果"}
          </button>
        </div>
      </header>

      {handoffVisible ? (
        <HandoffBanner
          handoff={handoff}
          onDismiss={() => setHandoffVisible(false)}
          onBack={goBackToSource}
          onRestart={restartWithoutHandoff}
        />
      ) : null}

      {notice ? (
        <div className="ak-notice" role="status">
          <span>{notice}</span>
          <button type="button" className="ak-link" onClick={() => setNotice("")}>
            知道了
          </button>
        </div>
      ) : null}

      <div className="ak-main">
        <aside className="ak-sessions" data-agentkit-sessions aria-label="会话列表">
          <SessionList
            conversations={conversations}
            activeId={activeConversation}
            onNew={startNew}
            onSelect={selectConversation}
          />
        </aside>

        <section className="ak-thread" data-agentkit-thread aria-label="对话">
          <Thread
            turns={workbench.turns}
            status={workbench.status}
            error={workbench.error}
            pendingChoice={workbench.pendingChoice}
            onChoose={choose}
            onRetry={() => {
              const lastUser = [...workbench.turns].reverse().find((turn) => turn.user);
              if (lastUser) send(lastUser.user);
            }}
          />
          <Composer />
        </section>

        <section className="ak-board" data-agentkit-board aria-label="分析结果">
          <Board items={items} turns={workbench.turns} sessionId={sessionId} status={workbench.status} />
        </section>
      </div>
    </div>
    </AssistantRuntimeProvider>
  );
}
