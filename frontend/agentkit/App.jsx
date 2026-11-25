import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AssistantRuntimeProvider} from "@assistant-ui/react";

import {chooseOption, listConversations, openConversation, saveConversation, streamChat, updateSources} from "./api.js";
import {
  applyEvent,
  createWorkbenchState,
  handoffConversationStorageKey,
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
import OntologyGraph from "./components/OntologyGraph.jsx";
import SessionList from "./components/SessionList.jsx";
import {SourceSettings} from "./components/Settings.jsx";
import SopBar from "./components/SopBar.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";
import {readSourcePreference, sourceSelection, writeSourcePreference} from "./sourcePreference.js";

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

export default function App({version}) {
  const handoff = useMemo(() => parseHandoff(window.location.search), []);
  const scope = useMemo(() => scopeFromHandoff(handoff), [handoff]);
  const [handoffVisible, setHandoffVisible] = useState(handoff.active);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [view, setView] = useState("thread");
  const [graphHit, setGraphHit] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [workbench, setWorkbench] = useState(() => createWorkbenchState());
  // A card handoff keeps one session across refreshes; free entry gets a new one.
  const [sessionId, setSessionId] = useState(
    () => resolveHandoffSession(handoff, safeSessionStorage()) || newSessionId(handoff),
  );
  const [sourcePreference, setSourcePreference] = useState(readSourcePreference);
  const [notice, setNotice] = useState("");
  const controllerRef = useRef(null);
  const contextVersion = useRef(0);
  const boundSourceSession = useRef("");
  const settingsSaving = useRef(false);
  const stateRef = useRef(workbench);
  const savedSnapshotRef = useRef("");
  const handoffRestoredRef = useRef(false);
  // Opening a stored conversation must never write: only a turn produced in
  // this page marks the conversation dirty (spec §6.1 打开旧会话).
  const dirtyRef = useRef(false);
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
    const onEvent = (event) => {
      if (controllerRef.current === controller) {
        setWorkbench((previous) => applyEvent(previous, event));
      }
    };
    try {
      await opener({sessionId: session, signal: controller.signal, onEvent});
    } catch (error) {
      if (error?.name !== "AbortError") onEvent({type: "error", message: error.message});
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
      runStream(sessionId, async (options) => {
        if (sourcePreference && boundSourceSession.current !== sessionId) {
          try {
            await updateSources(sessionId, sourcePreference, options.signal);
          } catch (error) {
            throw new Error(`绑定所选数据源失败：${error.message}`);
          }
          if (options.signal.aborted) return;
          boundSourceSession.current = sessionId;
        }
        dirtyRef.current = true;
        await streamChat({...options, message: value, scope});
      });
    },
    [runStream, scope, sessionId, sourcePreference],
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
      dirtyRef.current = true;
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

  const resetSession = useCallback((next) => {
    contextVersion.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    dirtyRef.current = false;
    savedSnapshotRef.current = "";
    const storageKey = handoffSessionStorageKey(handoff);
    const conversationKey = handoffConversationStorageKey(handoff);
    try {
      if (storageKey) safeSessionStorage()?.setItem(storageKey, next);
      if (conversationKey) safeSessionStorage()?.removeItem(conversationKey);
    } catch (_) {
      /* storage can be unavailable in hardened browsers */
    }
    setSessionId(next);
    setActiveConversation("");
    setGraphHit(null);
    setWorkbench(createWorkbenchState());
    setNotice("");
  }, [handoff]);

  const startNew = useCallback(() => resetSession(newSessionId(handoff)), [handoff, resetSession]);

  const applySourceSettings = useCallback(async (changes) => {
    if (settingsSaving.current || ["streaming", "paused"].includes(stateRef.current.status)) {
      throw new Error("请在当前分析结束后切换数据源。");
    }
    settingsSaving.current = true;
    const version = contextVersion.current;
    const next = newSessionId(handoff);
    try {
      const response = await updateSources(next, changes);
      if (contextVersion.current !== version || ["streaming", "paused"].includes(stateRef.current.status)) {
        throw new Error("当前会话已变化，请重新打开设置保存。");
      }
      const selection = sourceSelection({...changes, ...response});
      boundSourceSession.current = next;
      writeSourcePreference(selection);
      setSourcePreference(selection);
      resetSession(next);
      return selection;
    } finally {
      settingsSaving.current = false;
    }
  }, [handoff, resetSession]);

  const selectConversation = useCallback(async (cid, targetSession = newSessionId(null)) => {
    const version = ++contextVersion.current;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setGraphHit(null);
    try {
      // The session id travels with the restore: follow-up questions must land
      // in the analysis context this conversation was reopened into.
      const restored = await openConversation(cid, targetSession);
      if (contextVersion.current !== version) return;
      const nextSession = restored.sessionId || targetSession;
      dirtyRef.current = false;
      savedSnapshotRef.current = "";
      boundSourceSession.current = nextSession;
      setSessionId(nextSession);
      setActiveConversation(cid);
      setWorkbench({
        ...createWorkbenchState(),
        sessionId: nextSession,
        // Structured turns restore boards/evidence/hits; old records fall back
        // to the persisted messages.
        turns: turnsFromSnapshot(restored.agentkit) || hydrateTurns(restored.messages),
      });
      setNotice(restored.sourceRestoreError ? `历史数据源恢复失败：${restored.sourceRestoreError}` : "");
    } catch (error) {
      if (contextVersion.current === version) setNotice(`打开会话失败：${error.message}`);
    }
  }, []);

  // A refresh of the same card reopens the conversation it already produced
  // instead of showing an empty transcript with a reused session id.
  useEffect(() => {
    if (handoffRestoredRef.current || !handoff.handoffId) return;
    handoffRestoredRef.current = true;
    let cid = "";
    try {
      cid = safeSessionStorage()?.getItem(handoffConversationStorageKey(handoff)) || "";
    } catch (_) {
      cid = "";
    }
    if (cid) void selectConversation(cid, sessionId);
  }, [handoff, selectConversation, sessionId]);

  // Persist every completed turn so the conversation can be reopened with its
  // boards, evidence and ontology hits. Legacy (message-only) records keep
  // working through the messages fallback.
  useEffect(() => {
    if (!dirtyRef.current) return;
    if (!["idle", "error", "interrupted"].includes(workbench.status)) return;
    if (!workbench.turns.length || !sessionId) return;
    const snapshot = snapshotFromState(workbench);
    const fingerprint = JSON.stringify(snapshot);
    if (fingerprint === savedSnapshotRef.current) return;
    savedSnapshotRef.current = fingerprint;
    const version = contextVersion.current;
    const title = workbench.turns[0]?.user || "未命名对话";
    saveConversation({
      sessionId,
      cid: activeConversation || "",
      title,
      turns: snapshot.turns,
      handoff: scope,
    })
      .then((saved) => {
        if (contextVersion.current !== version) return;
        dirtyRef.current = false;
        if (saved.cid && saved.cid !== activeConversation) setActiveConversation(saved.cid);
        // Keep the card's conversation so a refresh reopens it instead of
        // showing an empty page with a reused session id.
        const conversationKey = handoffConversationStorageKey(handoff);
        if (conversationKey && saved.cid) {
          try {
            safeSessionStorage()?.setItem(conversationKey, saved.cid);
          } catch (_) {
            /* storage can be unavailable in hardened browsers */
          }
        }
        // The left list is server-driven: refresh so the new conversation shows
        // without a manual reload.
        void refreshConversations();
      })
      .catch(() => {
        /* saving history must never break the conversation */
      });
  }, [activeConversation, handoff, refreshConversations, scope, sessionId, workbench.status, workbench.turns]);

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

  const runtime = useAgentkitRuntime({
    turns: workbench.turns,
    running: workbench.status === "streaming",
    paused: workbench.status === "paused",
    onNew: send,
    onCancel: stop,
  });
  const busy = ["streaming", "paused"].includes(workbench.status);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
    <div className="ak-shell" data-agentkit-root="1" data-ak-view={view}>
      <div className="ak-main">
        <aside className="ak-sessions" data-agentkit-sessions aria-label="工作台导航">
          <header className="ak-brand">
            <span className="ak-brand-mark" aria-hidden="true">◆</span>
            <span className="ak-brand-name">智能分析</span>
            {version ? <span className="ak-brand-chip">{version}</span> : null}
          </header>
          <div className="ak-session-pane">
            <SessionList
              conversations={conversations}
              activeId={activeConversation}
              onNew={() => { startNew(); setView("thread"); }}
              onSelect={(cid) => { void selectConversation(cid); setView("thread"); }}
            />
          </div>
          <nav className="ak-nav-footer" aria-label="工作台视图">
            <div className="ak-mobile-nav" data-agentkit-layout-toggle>
              {[["sessions", "会话"], ["thread", "对话"], ["board", "看板"]].map(([key, label]) => (
                <button key={key} type="button" className="ak-ghost" aria-pressed={view === key}
                  onClick={() => setView(key)}>{label}</button>
              ))}
            </div>
            <button type="button" className="ak-ghost ak-source-trigger" aria-haspopup="dialog"
              onClick={() => setSettingsOpen(true)}>切换本体库/数据源</button>
          </nav>
        </aside>

        <section className="ak-thread" data-agentkit-thread aria-label="对话">
          <SopBar key={`sop:${sessionId}`} sop={workbench.turns.at(-1)?.sop} status={workbench.status} />
          {handoffVisible ? (
            <HandoffBanner
              handoff={handoff}
              confirmed={workbench.scopeConfirmed}
              onDismiss={() => setHandoffVisible(false)}
              onBack={goBackToSource}
              onRestart={restartWithoutHandoff}
            />
          ) : null}
          {notice ? (
            <div className="ak-notice" role="status">
              <span>{notice}</span>
              <button type="button" className="ak-link" onClick={() => setNotice("")}>知道了</button>
            </div>
          ) : null}
          <Thread
            key={sessionId}
            turns={workbench.turns}
            status={workbench.status}
            error={workbench.error}
            pendingChoice={workbench.pendingChoice}
            onChoose={choose}
            onOpenOntology={setGraphHit}
            onRetry={() => {
              const lastUser = [...workbench.turns].reverse().find((turn) => turn.user);
              if (lastUser) send(lastUser.user);
            }}
          />
          <Composer busy={busy} />
        </section>

        <section className="ak-board" data-agentkit-board aria-label="分析结果">
          <Board turns={workbench.turns} status={workbench.status} />
        </section>
      </div>
      {graphHit ? (
        <OntologyGraph hit={graphHit} sessionId={sessionId} onClose={() => setGraphHit(null)} />
      ) : null}
      {settingsOpen ? (
        <SourceSettings
          sessionId={sessionId}
          preference={workbench.turns.length ? null : sourcePreference}
          hasConversation={Boolean(activeConversation || workbench.turns.length)}
          busy={busy}
          onSaveSources={applySourceSettings}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}
    </div>
    </AssistantRuntimeProvider>
  );
}
