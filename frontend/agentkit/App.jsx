import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AssistantRuntimeProvider} from "@assistant-ui/react";

import {activateReports, chooseOption, historyAssets, listConversations, openConversation, reportStatus,
  requestJson, saveConversation, startReportGenerator, streamChat, updateReportConfig, updateSources} from "./api.js";
import {
  applyEvent,
  createWorkbenchState,
  handoffConversationStorageKey,
  handoffSessionStorageKey,
  parseHandoff,
  resolveHandoffSession,
  resumeTurn,
  scopeFromHandoff,
  snapshotFromState,
  startTurn,
  stopTurn,
} from "./state.js";
import Board from "./components/Board.jsx";
import Composer from "./components/Composer.jsx";
import HandoffBanner from "./components/HandoffBanner.jsx";
import OntologyGraph from "./components/OntologyGraph.jsx";
import PanelDivider from "./components/PanelDivider.jsx";
import ReportControls from "./components/ReportControls.jsx";
import SessionList from "./components/SessionList.jsx";
import {SourceSettings} from "./components/Settings.jsx";
import SopBar from "./components/SopBar.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";
import {readSourcePreference, sourceSelection, writeSourcePreference} from "./sourcePreference.js";
import {restoreTurns} from "./history.js";
import {readPreferences, writePreferences} from "./preferences.js";

const emptyReport = {active_reports: [], with_db: true, has_session: false};
const initialMode = () => new URLSearchParams(window.location.search).get("mode") === "report" ? "report" : "data";

function panelPreference(key, defaultValue, min, max) {
  try {
    const value = Number(localStorage.getItem(key));
    return value >= min && value <= max ? value : defaultValue;
  } catch { return defaultValue; }
}

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
  const [mode, setMode] = useState(initialMode);
  const [report, setReport] = useState(emptyReport);
  const [reportRevision, setReportRevision] = useState(0);
  const [opening, setOpening] = useState(false);
  const [preferences, setPreferences] = useState(readPreferences);
  const [sidebarWidth, setSidebarWidth] = useState(() => panelPreference("bi.layout.sidebarWidth", 224, 176, 320));
  const [threadWidth, setThreadWidth] = useState(() => panelPreference("agentkit.layout.threadPercent", 42, 32, 48));
  const [jump, setJump] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [view, setView] = useState("thread");
  const [graphHit, setGraphHit] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [workbench, setWorkbench] = useState(() => createWorkbenchState());
  // A card handoff keeps one session across refreshes; free entry gets a new one.
  const [sessionId, setSessionId] = useState(
    () => (mode === "data" && resolveHandoffSession(handoff, safeSessionStorage())) || newSessionId(mode === "data" ? handoff : null),
  );
  const [sourcePreference, setSourcePreference] = useState(readSourcePreference);
  const [notice, setNotice] = useState("");
  const controllerRef = useRef(null);
  const openingRef = useRef(false);
  const contextVersion = useRef(0);
  const modeContexts = useRef({});
  const listVersion = useRef(0);
  const boundSourceSession = useRef("");
  const boundRoles = useRef(new Set());
  const settingsSaving = useRef(false);
  const sourceOverrides = useRef({});
  const stateRef = useRef(workbench);
  const savedSnapshotRef = useRef("");
  const savedIds = useRef(new Map());
  const savingSnapshots = useRef(new Map());
  const latestSnapshot = useRef("");
  const handoffRestoredRef = useRef(false);
  // Opening a stored conversation must never write: only a turn produced in
  // this page marks the conversation dirty (spec §6.1 打开旧会话).
  const dirtyRef = useRef(false);
  stateRef.current = workbench;

  useEffect(() => {
    try {
      localStorage.setItem("bi.layout.sidebarWidth", String(sidebarWidth));
      localStorage.setItem("agentkit.layout.threadPercent", String(threadWidth));
    } catch { /* restricted browser storage */ }
  }, [sidebarWidth, threadWidth]);

  const refreshConversations = useCallback(async () => {
    const version = ++listVersion.current;
    try {
      const items = await listConversations(mode);
      if (version === listVersion.current) setConversations(items);
    } catch (error) {
      if (version === listVersion.current) setNotice(`会话列表加载失败：${error.message}`);
    }
  }, [mode]);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  const runStream = useCallback(async (session, opener, choice = false) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    const onEvent = (event) => {
      if (controllerRef.current === controller) {
        setWorkbench((previous) => applyEvent(previous, choice && previous.submittingChoice &&
          ["error", "stream_interrupted"].includes(event.type)
          ? {type: "choice_failed", message: event.message || "补充条件提交失败，请重试。"} : event));
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

  const ensureSettings = useCallback(async (target, signal) => {
    if (sourcePreference && boundSourceSession.current !== target) {
      try { await updateSources(target, {...sourcePreference, ...sourceOverrides.current}, signal); }
      catch (error) { throw new Error(`绑定所选数据源失败：${error.message}`); }
      if (signal?.aborted) return;
      boundSourceSession.current = target;
    }
    if (!boundRoles.current.has(target) && (preferences.user_role !== undefined || preferences.agent_pref !== undefined)) {
      await requestJson("api/roles", {method: "PUT", signal, body: {
        session_id: target, user_role: preferences.user_role || "", agent_pref: preferences.agent_pref || "",
      }});
      boundRoles.current.add(target);
    }
  }, [sourcePreference, preferences.user_role, preferences.agent_pref]);

  const send = useCallback(
    (text, {target = sessionId, message = text, reportReady = report.has_session} = {}) => {
      const value = String(text || "").trim();
      if (!value || controllerRef.current || stateRef.current.status === "paused" || openingRef.current) return;
      if (mode === "report" && !reportReady) {
        setNotice("请先启用报表附件，或开启标准报表生成。");
        return;
      }
      setNotice("");
      setWorkbench((previous) => startTurn(previous, {text: value, sessionId: target}));
      runStream(target, async (options) => {
        await ensureSettings(target, options.signal);
        if (options.signal.aborted) return;
        dirtyRef.current = true;
        await streamChat({...options, message, visibleText: value, scope, mode});
      });
    },
    [ensureSettings, mode, report.has_session, runStream, scope, sessionId],
  );

  const choose = useCallback(
    (picked) => {
      const pending = stateRef.current.pendingChoice;
      const chosen = Array.isArray(picked) ? picked : picked ? [picked] : [];
      if (!pending || !chosen.length || controllerRef.current) return;
      // AskUser supports multi-select: keep the ids/labels order the user picked.
      const ids = chosen.map((option) => String(option.id ?? option.label ?? ""));
      const labels = chosen.map((option) => String(option.label ?? option.id ?? ""));
      // /api/choice resumes with a NEW request turn_id; release the old one so
      // the continuation is not filtered out as stale.
      dirtyRef.current = true;
      setWorkbench((previous) => resumeTurn(previous, chosen.map((_, index) => ({id: ids[index], label: labels[index]}))));
      runStream(sessionId, (options) => chooseOption({...options, ids, labels, mode}), true);
    },
    [mode, runStream, sessionId],
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
    const storageKey = mode === "data" && handoffSessionStorageKey(handoff);
    const conversationKey = mode === "data" && handoffConversationStorageKey(handoff);
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
    setReport(emptyReport);
    setJump(null);
    setNotice("");
  }, [handoff, mode]);

  const startNew = useCallback(() => resetSession(newSessionId(mode === "data" ? handoff : null)), [handoff, mode, resetSession]);

  const switchMode = (nextMode) => {
    if (nextMode === mode || controllerRef.current || opening || settingsSaving.current) return;
    modeContexts.current[mode] = {sessionId, activeConversation, workbench, report, draft: runtime.thread.composer.getState().text,
      savedSnapshot: savedSnapshotRef.current,
      dirty: dirtyRef.current, boundSource: boundSourceSession.current};
    const next = modeContexts.current[nextMode];
    contextVersion.current += 1;
    listVersion.current += 1;
    setMode(nextMode);
    setConversations([]);
    setView("thread");
    setJump(null);
    setGraphHit(null);
    setNotice("");
    setSessionId(next?.sessionId || newSessionId(null));
    setActiveConversation(next?.activeConversation || savedIds.current.get(next?.sessionId) || "");
    setWorkbench(next?.workbench || createWorkbenchState());
    setReport(next?.report || emptyReport);
    runtime.thread.composer.setText(next?.draft || "");
    savedSnapshotRef.current = next?.savedSnapshot || "";
    dirtyRef.current = next?.dirty || false;
    boundSourceSession.current = next?.boundSource || "";
    const url = new URL(window.location.href);
    if (nextMode === "report") url.searchParams.set("mode", "report");
    else url.searchParams.delete("mode");
    window.history.replaceState(window.history.state, "", url);
  };

  const activateReport = async (ids, withDb) => {
    await ensureSettings(sessionId);
    const restored = await activateReports(sessionId, ids, withDb, activeConversation && !report.has_session ? activeConversation : "");
    setReport({...restored, has_session: true});
    if (activeConversation && stateRef.current.turns.length) {
      dirtyRef.current = true;
      setReportRevision((revision) => revision + 1);
    }
  };

  const generateReport = async (prompt) => {
    const target = newSessionId(null);
    await ensureSettings(target);
    await startReportGenerator(target);
    resetSession(target);
    setReport({...emptyReport, has_session: true});
    send("生成标准报表", {target, message: prompt, reportReady: true});
  };

  const setReportDatabase = async (withDb) => {
    const version = contextVersion.current;
    if (report.has_session) await updateReportConfig(sessionId, withDb);
    if (contextVersion.current !== version) return;
    setReport((previous) => ({...previous, with_db: withDb}));
    if (report.has_session && activeConversation && stateRef.current.turns.length) {
      dirtyRef.current = true;
      setReportRevision((revision) => revision + 1);
    }
  };

  const applyPreferences = async (values) => {
    const saved = await requestJson("api/roles", {method: "PUT", body: {
      session_id: sessionId, user_role: values.user_role || "", agent_pref: values.agent_pref || "",
    }});
    const next = {...values, user_role: saved.user_role || "", agent_pref: saved.agent_pref || ""};
    // Other open mode contexts pick up the new defaults at their next turn.
    boundRoles.current = new Set([sessionId]);
    writePreferences(next);
    const url = new URL(window.location.href);
    if (url.searchParams.has("theme")) {
      url.searchParams.delete("theme");
      window.history.replaceState(window.history.state, "", url);
    }
    setPreferences(next);
  };

  const applySourceSettings = useCallback(async (changes) => {
    if (settingsSaving.current || ["streaming", "paused"].includes(stateRef.current.status)) {
      throw new Error("请在当前分析结束后切换数据源。");
    }
    settingsSaving.current = true;
    const version = contextVersion.current;
    const next = newSessionId(mode === "data" ? handoff : null);
    try {
      const response = await updateSources(next, changes);
      if (contextVersion.current !== version || ["streaming", "paused"].includes(stateRef.current.status)) {
        throw new Error("当前会话已变化，请重新打开设置保存。");
      }
      const selection = sourceSelection({...changes, ...response});
      const connection = Object.fromEntries(Object.entries(changes)
        .filter(([name, value]) => name.startsWith("doris_") && name !== "doris_database" && value
          && value !== "（已配置，见服务端环境变量）"));
      sourceOverrides.current = selection.database === sourcePreference?.database
        ? {...sourceOverrides.current, ...connection} : connection;
      boundSourceSession.current = next;
      writeSourcePreference(selection);
      setSourcePreference(selection);
      resetSession(next);
      return selection;
    } finally {
      settingsSaving.current = false;
    }
  }, [handoff, mode, resetSession, sourcePreference]);

  const selectConversation = useCallback(async (cid, targetSession = newSessionId(null)) => {
    const version = ++contextVersion.current;
    controllerRef.current?.abort();
    controllerRef.current = null;
    setGraphHit(null);
    openingRef.current = true;
    setOpening(true);
    try {
      // The session id travels with the restore: follow-up questions must land
      // in the analysis context this conversation was reopened into.
      const [restored, legacy] = await Promise.all([
        openConversation(cid, targetSession),
        historyAssets(cid).then((assets) => ({assets}), (error) => ({error: error.message})),
      ]);
      if (contextVersion.current !== version) return;
      const nextSession = restored.sessionId || targetSession;
      const reportContext = restored.mode === "report"
        ? await reportStatus(nextSession).catch((error) => ({...emptyReport, error: error.message})) : emptyReport;
      if (contextVersion.current !== version) return;
      dirtyRef.current = false;
      savedSnapshotRef.current = "";
      boundSourceSession.current = nextSession;
      setSessionId(nextSession);
      setActiveConversation(cid);
      setReport(reportContext);
      setJump(null);
      const pendingChoice = restored.awaitingChoice ? restored.agentkit?.pendingChoice : null;
      const turns = restoreTurns(restored.agentkit, restored.messages, legacy.assets);
      const last = turns.at(-1);
      if (!pendingChoice && last?.status === "paused") last.status = "interrupted";
      setWorkbench({
        ...createWorkbenchState(),
        sessionId: nextSession,
        turns,
        ...(pendingChoice ? {status: "paused", pendingChoice} : {}),
      });
      setNotice([
        restored.sourceRestoreError && `历史数据源恢复失败：${restored.sourceRestoreError}`,
        (restored.reportRestoreError || reportContext.error) && `报表上下文恢复失败：${restored.reportRestoreError || reportContext.error}`,
        restored.mode === "report" && !reportContext.has_session && !restored.reportRestoreError &&
          "这条历史没有可恢复的报表附件。重新选择原报表后，可以在现有对话继续提问。",
        legacy.error && `旧版回看内容加载失败：${legacy.error}`,
      ].filter(Boolean).join(" · "));
    } catch (error) {
      if (contextVersion.current === version) setNotice(`打开会话失败：${error.message}`);
    } finally {
      if (contextVersion.current === version) {
        openingRef.current = false;
        setOpening(false);
      }
    }
  }, []);

  // A refresh of the same card reopens the conversation it already produced
  // instead of showing an empty transcript with a reused session id.
  useEffect(() => {
    if (mode !== "data" || handoffRestoredRef.current || !handoff.handoffId) return;
    handoffRestoredRef.current = true;
    let cid = "";
    try {
      cid = safeSessionStorage()?.getItem(handoffConversationStorageKey(handoff)) || "";
    } catch (_) {
      cid = "";
    }
    if (cid) void selectConversation(cid, sessionId);
  }, [handoff, mode, selectConversation, sessionId]);

  useEffect(() => {
    if (openingRef.current || controllerRef.current || (mode === "report" && !report.has_session)) return;
    const url = new URL(window.location.href);
    const prompt = url.searchParams.get("prompt")?.trim();
    if (!prompt) return;
    url.searchParams.delete("prompt");
    window.history.replaceState(window.history.state, "", url);
    send(prompt);
  }, [mode, opening, report.has_session, send]);

  // Persist every completed turn so the conversation can be reopened with its
  // boards, evidence and ontology hits. Legacy (message-only) records keep
  // working through the messages fallback.
  useEffect(() => {
    if (!dirtyRef.current) return;
    if (!["idle", "error", "interrupted", "paused"].includes(workbench.status)) return;
    if (!workbench.turns.length || !sessionId) return;
    const snapshot = snapshotFromState(workbench);
    const fingerprint = JSON.stringify([snapshot, workbench.pendingChoice, workbench.generation, reportRevision]);
    latestSnapshot.current = fingerprint;
    if (fingerprint === savedSnapshotRef.current) return;
    savedSnapshotRef.current = fingerprint;
    const version = contextVersion.current;
    const title = workbench.turns[0]?.user || "未命名对话";
    const previousSave = savingSnapshots.current.get(sessionId) || Promise.resolve();
    const saving = previousSave.catch(() => {}).then(() => saveConversation({
      sessionId,
      cid: activeConversation || savedIds.current.get(sessionId) || "",
      title,
      turns: snapshot.turns,
      pendingChoice: workbench.pendingChoice,
      generation: workbench.generation,
      handoff: mode === "data" ? scope : null,
      mode,
    }));
    savingSnapshots.current.set(sessionId, saving);
    saving
      .then((saved) => {
        if (saved.cid) savedIds.current.set(sessionId, saved.cid);
        if (contextVersion.current !== version) return;
        if (latestSnapshot.current === fingerprint) dirtyRef.current = false;
        if (saved.cid && saved.cid !== activeConversation) setActiveConversation(saved.cid);
        // Keep the card's conversation so a refresh reopens it instead of
        // showing an empty page with a reused session id.
        const conversationKey = mode === "data" && handoffConversationStorageKey(handoff);
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
      .catch((error) => {
        if (contextVersion.current === version) setNotice(`会话保存失败：${error.message}`);
      })
      .finally(() => {
        if (savingSnapshots.current.get(sessionId) === saving) savingSnapshots.current.delete(sessionId);
      });
  }, [activeConversation, handoff, mode, refreshConversations, scope, sessionId, workbench.status, workbench.turns,
    workbench.pendingChoice, workbench.generation, reportRevision]);

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
  const blocked = busy || opening;
  const jumpTo = (id) => {
    setView("thread");
    setJump({id});
  };
  const prefill = (prompt) => {
    runtime.thread.composer.setText(prompt);
    setView("thread");
    requestAnimationFrame(() => document.querySelector(".ak-composer-input")?.focus());
  };

  return (
    <AssistantRuntimeProvider runtime={runtime}>
    <div className="ak-shell" data-agentkit-root="1" data-ak-view={view}
      data-theme={new URLSearchParams(window.location.search).get("theme") || preferences.theme}>
      <div className="ak-main" style={{"--ak-sidebar-width": `${sidebarWidth}px`, "--ak-thread-ratio": threadWidth / 100}}>
        <aside className="ak-sessions" data-agentkit-sessions aria-label="工作台导航">
          <header className="ak-brand">
            <span className="ak-brand-mark" aria-hidden="true">◆</span>
            <span className="ak-brand-name">智能分析</span>
            {version ? <span className="ak-brand-chip">{version}</span> : null}
          </header>
          <nav className="ak-modes" aria-label="分析模式">
            {[["data", "智能分析"], ["report", "报表分析"]].map(([key, label]) =>
              <button key={key} type="button" className="ak-ghost" aria-pressed={mode === key}
                disabled={blocked} onClick={() => switchMode(key)}>{label}</button>)}
          </nav>
          <div className="ak-session-pane">
            <SessionList
              key={mode}
              conversations={conversations}
              activeId={activeConversation}
              busy={blocked || Boolean(activeConversation && savingSnapshots.current.get(sessionId))}
              onNew={() => { startNew(); runtime.thread.composer.setText(""); setView("thread"); }}
              onSelect={(cid) => { void selectConversation(cid); setView("thread"); }}
              onRefresh={refreshConversations}
              onRemoved={(cid) => { if (cid === activeConversation) startNew(); }}
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
          {workbench.turns.some((turn) => turn.user) ? <nav className="ak-question-rail" aria-label="问题定位">
            {workbench.turns.map((turn, index) => turn.user && <button type="button" key={turn.id}
              className="ak-ghost" title={turn.user} aria-current={jump?.id === turn.id ? "location" : undefined}
              aria-label={`第 ${index + 1} 轮：${turn.user}`}
              onClick={() => jumpTo(turn.id)}>{index + 1}. {turn.user}</button>)}
          </nav> : null}
          {mode === "report" ? <ReportControls key={`report:${sessionId}`} context={report} busy={blocked}
            onActivate={activateReport} onWithDb={setReportDatabase} onGenerate={generateReport} onDetach={startNew} /> : null}
          {handoffVisible && mode === "data" ? (
            <HandoffBanner
              handoff={handoff}
              confirmed={workbench.scopeConfirmed}
              onDismiss={() => setHandoffVisible(false)}
              onBack={goBackToSource}
              onRestart={restartWithoutHandoff}
            />
          ) : null}
          {opening ? <div className="ak-notice" role="status">正在打开历史会话…</div> : null}
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
            mode={mode}
            name={preferences.name}
            jump={jump}
            onPrefill={prefill}
            onChoose={choose}
            onStop={stop}
            onOpenOntology={setGraphHit}
            onRetry={() => {
              const lastUser = [...workbench.turns].reverse().find((turn) => turn.user);
              if (lastUser) send(lastUser.user);
            }}
          />
          <Composer busy={blocked} mode={mode} sessionId={sessionId} onSavePreferences={applyPreferences} />
        </section>

        <section className="ak-board" data-agentkit-board aria-label="分析结果">
          <Board turns={workbench.turns} status={workbench.status} onJump={jumpTo}
            onInsight={mode === "data" || (report.with_db && report.has_session) ? send : null}
            onPrefill={prefill} busy={blocked} />
        </section>
        <PanelDivider name="调整导航栏宽度" kind="sidebar" value={sidebarWidth} min={176} max={320} onChange={setSidebarWidth} />
        <PanelDivider name="调整对话栏与看板栏宽度" kind="thread" value={threadWidth} min={32} max={48} onChange={setThreadWidth} />
      </div>
      {graphHit ? (
        <OntologyGraph hit={graphHit} sessionId={sessionId} onClose={() => setGraphHit(null)} />
      ) : null}
      {settingsOpen ? (
        <SourceSettings
          sessionId={sessionId}
          preference={workbench.turns.length ? null : sourcePreference}
          hasConversation={Boolean(activeConversation || workbench.turns.length)}
          busy={blocked}
          onSaveSources={applySourceSettings}
          onClose={() => setSettingsOpen(false)}
        />
      ) : null}
    </div>
    </AssistantRuntimeProvider>
  );
}
