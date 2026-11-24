import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AssistantRuntimeProvider} from "@assistant-ui/react";

import {chooseOption, listConversations, openConversation, saveConversation, streamChat} from "./api.js";
import {
  applyEvent,
  boardItems,
  createWorkbenchState,
  handoffSessionStorageKey,
  hydrateTurns,
  parseHandoff,
  resolveHandoffSession,
  resumeTurn,
  scopeFromHandoff,
  snapshotFromState,
  startTurn,
  stopTurn,
  turnsFromSnapshot,
} from "./state.js";
import Board from "./components/Board.jsx";
import Composer from "./components/Composer.jsx";
import HandoffBanner from "./components/HandoffBanner.jsx";
import SessionList from "./components/SessionList.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";

function safeSessionStorage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function newSessionId(handoff) {
  const stamp = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return handoff?.handoffId ? `agentkit-${handoff.handoffId}-${stamp}` : `agentkit-${stamp}`;
}

export default function App() {
  const handoff = useMemo(() => parseHandoff(window.location.search), []);
  const scope = useMemo(() => scopeFromHandoff(handoff), [handoff]);
  const [handoffVisible, setHandoffVisible] = useState(handoff.active);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [view, setView] = useState("split");
  const [workbench, setWorkbench] = useState(() => createWorkbenchState());
  // A card handoff keeps one session across refreshes; free entry gets a new one.
  const [sessionId, setSessionId] = useState(
    () => resolveHandoffSession(handoff, safeSessionStorage()) || newSessionId(handoff),
  );
  const [notice, setNotice] = useState("");
  const controllerRef = useRef(null);
  const stateRef = useRef(workbench);
  const savedSnapshotRef = useRef("");
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
      runStream(sessionId, (options) => streamChat({...options, message: value, scope}));
    },
    [runStream, scope, sessionId],
  );

  const choose = useCallback(
    (picked) => {
      const pending = stateRef.current.pendingChoice;
      const chosen = Array.isArray(picked) ? picked : picked ? [picked] : [];
      if (!pending || !chosen.length) return;
      // AskUser supports multi-select: keep the ids/labels order the user picked.
      const ids = chosen.map((option) => String(option.id ?? option.label ?? ""));
      const labels = chosen.map((option) => String(option.label ?? option.id ?? ""));
      // /api/choice resumes with a NEW request turn_id; release the old one so
      // the continuation is not filtered out as stale.
      setWorkbench((previous) => resumeTurn(previous));
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
    const storageKey = handoffSessionStorageKey(handoff);
    if (storageKey) {
      try {
        safeSessionStorage()?.setItem(storageKey, next);
      } catch (_) {
        /* storage can be unavailable in hardened browsers */
      }
    }
    setSessionId(next);
    setActiveConversation("");
    setWorkbench(createWorkbenchState());
    setNotice("");
  }, [handoff]);

  const selectConversation = useCallback(async (cid) => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    try {
      // The session id travels with the restore: follow-up questions must land
      // in the analysis context this conversation was reopened into.
      const restored = await openConversation(cid, sessionId);
      const nextSession = restored.sessionId || sessionId || cid;
      setSessionId(nextSession);
      setActiveConversation(cid);
      setWorkbench({
        ...createWorkbenchState(),
        sessionId: nextSession,
        // Structured turns restore boards/evidence/hits; old records fall back
        // to the persisted messages.
        turns: turnsFromSnapshot(restored.agentkit) || hydrateTurns(restored.messages),
      });
      setNotice("");
    } catch (error) {
      setNotice(`打开会话失败：${error.message}`);
    }
  }, []);

  // Persist every completed turn so the conversation can be reopened with its
  // boards, evidence and ontology hits. Legacy (message-only) records keep
  // working through the messages fallback.
  useEffect(() => {
    if (!["idle", "error", "interrupted"].includes(workbench.status)) return;
    if (!workbench.turns.length || !sessionId) return;
    const snapshot = snapshotFromState(workbench);
    const fingerprint = JSON.stringify(snapshot);
    if (fingerprint === savedSnapshotRef.current) return;
    savedSnapshotRef.current = fingerprint;
    const title = workbench.turns[0]?.user || "未命名对话";
    saveConversation({
      sessionId,
      cid: activeConversation || "",
      title,
      turns: snapshot.turns,
      handoff: scope,
    })
      .then((saved) => {
        if (saved.cid && saved.cid !== activeConversation) setActiveConversation(saved.cid);
      })
      .catch(() => {
        /* saving history must never break the conversation */
      });
  }, [activeConversation, scope, sessionId, workbench.status, workbench.turns]);

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
    paused: workbench.status === "paused",
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
