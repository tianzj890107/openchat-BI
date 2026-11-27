import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {AssistantRuntimeProvider} from "@assistant-ui/react";

import {chooseOption, historyAssets, listConversations, openConversation, reportStatus,
  requestJson, saveConversation, startReportGenerator, streamChat, updateReportAttachments, updateReportConfig, updateSources,
  uploadReport} from "./api.js";
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
import SessionList from "./components/SessionList.jsx";
import {SourceSettings} from "./components/Settings.jsx";
import SopBar from "./components/SopBar.jsx";
import Thread from "./components/Thread.jsx";
import {useAgentkitRuntime} from "./runtime.js";
import {readSourcePreference, sourceSelection, writeSourcePreference} from "./sourcePreference.js";
import {restoreTurns} from "./history.js";
import {readPreferences, writePreferences} from "./preferences.js";

const emptyReport = {active_reports: [], with_db: true, has_session: false};

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

export default function App({version, assistant = false}) {
  const handoff = useMemo(() => parseHandoff(window.location.search), []);
  const scope = useMemo(() => scopeFromHandoff(handoff), [handoff]);
  const [handoffVisible, setHandoffVisible] = useState(handoff.active);
  const [recordMode, setRecordMode] = useState("data");
  const [report, setReport] = useState(emptyReport);
  const runtimeMode = report.has_session ? "report" : "data";
  const [reportChanging, setReportChanging] = useState(false);
  const [reportRevision, setReportRevision] = useState(0);
  const [opening, setOpening] = useState(false);
  const [preferences, setPreferences] = useState(readPreferences);
  const [sidebarWidth, setSidebarWidth] = useState(() => panelPreference("bi.layout.sidebarWidth", 224, 176, 320));
  const [threadWidth, setThreadWidth] = useState(() => panelPreference("agentkit.layout.threadPercent", 42, 32, 48));
  const [jump, setJump] = useState(null);
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState("");
  const [view, setView] = useState(() => (
    assistant && new URLSearchParams(window.location.search).get("view") === "board" ? "board" : "thread"
  ));
  const [graphHit, setGraphHit] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [assistantModel, setAssistantModel] = useState("");
  const [workbench, setWorkbench] = useState(() => createWorkbenchState());
  // A card handoff keeps one session across refreshes; free entry gets a new one.
  const [sessionId, setSessionId] = useState(() => {
    if (assistant) {
      try {
        const stored = window.sessionStorage.getItem("chuxiaoce.assistant.session");
        if (stored) return stored;
      } catch { /* restricted storage */ }
    }
    return resolveHandoffSession(handoff, safeSessionStorage()) || newSessionId(handoff);
  });
  const [sourcePreference, setSourcePreference] = useState(readSourcePreference);
  const [notice, setNotice] = useState("");
  const controllerRef = useRef(null);
  const openingRef = useRef(false);
  const contextVersion = useRef(0);
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
      const items = await listConversations();
      if (version === listVersion.current) setConversations(items);
    } catch (error) {
      if (version === listVersion.current) setNotice(`会话列表加载失败：${error.message}`);
    }
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  useEffect(() => {
    if (!assistant) return;
    try {
      window.sessionStorage.setItem("chuxiaoce.assistant.session", sessionId);
    } catch { /* restricted storage */ }
  }, [assistant, sessionId]);

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
    (text, {message = text, context = report} = {}) => {
      const value = String(text || "").trim();
      if (!value || controllerRef.current || stateRef.current.status === "paused" || openingRef.current || settingsSaving.current) return;
      const mode = context.has_session ? "report" : "data";
      const attachments = (context.active_reports || []).map((file) => file.filename || file.id);
      setNotice("");
      setWorkbench((previous) => startTurn(previous, {text: value, sessionId, attachments}));
      runStream(sessionId, async (options) => {
        if (!assistant) await ensureSettings(sessionId, options.signal);
        if (options.signal.aborted) return;
        dirtyRef.current = true;
        await streamChat({...options, message, visibleText: value, scope, mode});
      });
    },
    [assistant, ensureSettings, report, runStream, scope, sessionId],
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
      runStream(sessionId, (options) => chooseOption({...options, ids, labels, mode: runtimeMode}), true);
    },
    [runStream, runtimeMode, sessionId],
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
    setRecordMode("data");
    setGraphHit(null);
    setWorkbench(createWorkbenchState());
    setReport(emptyReport);
    setJump(null);
    setNotice("");
  }, [handoff]);

  const startNew = useCallback(() => resetSession(newSessionId(handoff)), [handoff, resetSession]);

  const changeReportContext = async (operation) => {
    if (settingsSaving.current || openingRef.current || controllerRef.current || stateRef.current.status === "paused") {
      throw new Error("请在当前分析结束后变更附件。");
    }
    settingsSaving.current = true;
    setReportChanging(true);
    try {
      // A saved round belongs to the executor that produced it. Wait before
      // replacing that executor and invalidating its generation.
      await savingSnapshots.current.get(sessionId)?.catch(() => {});
      await ensureSettings(sessionId);
      const context = await operation();
      setReport(context);
      if (stateRef.current.turns.length) {
        dirtyRef.current = true;
        setWorkbench((previous) => ({...previous, generation: undefined}));
        setReportRevision((revision) => revision + 1);
      }
      return context;
    } finally {
      settingsSaving.current = false;
      setReportChanging(false);
    }
  };

  const setAttachments = (ids) => changeReportContext(
    () => updateReportAttachments(sessionId, ids, report.with_db, runtimeMode),
  );

  const uploadAttachments = async (files) => {
    const ids = (report.active_reports || []).map((file) => file.id);
    if (ids.length + files.length > 5) throw new Error("最多同时使用五份附件，请先移除部分文件。");
    const failures = [];
    await changeReportContext(async () => {
      const uploaded = [];
      for (const file of files) {
        try { uploaded.push((await uploadReport(file)).id); }
        catch (error) { failures.push(`${file.name} · ${error.message}`); }
      }
      if (!uploaded.length) throw new Error(failures.join("；"));
      return updateReportAttachments(sessionId, [...new Set([...ids, ...uploaded])], report.with_db, runtimeMode);
    });
    return failures.join("；");
  };

  const generateReport = async (prompt) => {
    const context = await changeReportContext(async () => ({
      ...emptyReport,
      ...await startReportGenerator(sessionId, runtimeMode),
      has_session: true,
    }));
    send("生成标准报表", {message: prompt, context});
  };

  const setReportDatabase = (withDb) => changeReportContext(async () => {
    await updateReportConfig(sessionId, withDb);
    return {...report, with_db: withDb};
  });

  const applyPreferences = async (values) => {
    const saved = await requestJson("api/roles", {method: "PUT", body: {
      session_id: sessionId, user_role: values.user_role || "", agent_pref: values.agent_pref || "",
    }});
    const next = {...values, user_role: saved.user_role || "", agent_pref: saved.agent_pref || ""};
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
    const next = newSessionId(handoff);
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
  }, [handoff, resetSession, sourcePreference]);

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
      const reportContext = restored.runtimeMode === "report"
        ? (restored.reportContext || await reportStatus(nextSession)
          .catch((error) => ({...emptyReport, has_session: true, error: error.message}))) : emptyReport;
      if (contextVersion.current !== version) return;
      dirtyRef.current = false;
      savedSnapshotRef.current = "";
      boundSourceSession.current = nextSession;
      setSessionId(nextSession);
      setActiveConversation(cid);
      setRecordMode(restored.mode);
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

  const restoredAssistant = useRef(false);
  useEffect(() => {
    if (!assistant || restoredAssistant.current) return;
    let id = "";
    try { id = window.sessionStorage.getItem("chuxiaoce.assistant.session") || ""; } catch { id = ""; }
    if (!id) return;
    restoredAssistant.current = true;
    void selectConversation(id, id);
  }, [assistant, selectConversation]);

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

  useEffect(() => {
    if (openingRef.current || controllerRef.current || settingsSaving.current) return;
    const url = new URL(window.location.href);
    const prompt = url.searchParams.get("prompt")?.trim();
    if (!prompt) return;
    url.searchParams.delete("prompt");
    window.history.replaceState(window.history.state, "", url);
    send(prompt);
  }, [opening, send]);

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
      handoff: scope,
      mode: recordMode,
      runtimeMode,
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
      .catch((error) => {
        if (contextVersion.current === version) setNotice(`会话保存失败：${error.message}`);
      })
      .finally(() => {
        if (savingSnapshots.current.get(sessionId) === saving) savingSnapshots.current.delete(sessionId);
      });
  }, [activeConversation, handoff, recordMode, runtimeMode, refreshConversations, scope, sessionId, workbench.status, workbench.turns,
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

  const postHost = useCallback((payload) => {
    window.parent?.postMessage(payload, window.location.origin);
  }, []);

  useEffect(() => {
    if (!assistant) return undefined;
    let cancelled = false;
    requestJson("api/meta").then((meta) => {
      if (!cancelled) setAssistantModel(String(meta?.agent?.model || "团队模型"));
    }, () => {});
    return () => { cancelled = true; };
  }, [assistant]);

  useEffect(() => {
    if (!assistant) return undefined;
    const origin = window.location.origin;
    postHost({source: "cockpit-assistant", type: "ready"});
    const currentView = () => (view === "board" ? "board" : "chat");
    const onMessage = (event) => {
      if (event.origin !== origin || event.source !== window.parent) return;
      const data = event.data;
      if (data?.source !== "cockpit-assistant") return;
      if (data.type === "view") setView(data.view === "board" ? "board" : "thread");
      else if (data.type === "ready") postHost({source: "cockpit-assistant", type: "view", view: currentView()});
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [assistant, postHost, view]);

  const runtime = useAgentkitRuntime({
    turns: workbench.turns,
    running: workbench.status === "streaming",
    paused: workbench.status === "paused" || opening || reportChanging,
    onNew: send,
    onCancel: stop,
  });
  const busy = ["streaming", "paused"].includes(workbench.status);
  const blocked = busy || opening || reportChanging;
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
            <span className="ak-brand-name">{assistant ? "储小策智能助手" : "智能分析"}</span>
            {version ? <span className="ak-brand-chip">{version}</span> : null}
          </header>
          <div className="ak-session-pane">
            <SessionList
              conversations={conversations}
              activeId={activeConversation}
              busy={blocked || Boolean(activeConversation && savingSnapshots.current.get(sessionId))}
              onNew={() => { startNew(); runtime.thread.composer.setText(""); setView("thread"); }}
              onSelect={(cid) => { void selectConversation(cid); setView("thread"); }}
              onRefresh={refreshConversations}
            />
          </div>
          <nav className="ak-nav-footer" aria-label="工作台视图">
            <div className="ak-mobile-nav" data-agentkit-layout-toggle>
              {[["sessions", "会话"], ["thread", "对话"], ["board", "看板"]].map(([key, label]) => (
                <button key={key} type="button" className="ak-ghost" aria-pressed={view === key}
                  onClick={() => setView(key)}>{label}</button>
              ))}
            </div>
            {assistant ? (
              <button type="button" className="ak-ghost ak-source-trigger" aria-haspopup="dialog"
                onClick={() => setSettingsOpen(true)}>本体库/数据源（只读）</button>
            ) : (
              <button type="button" className="ak-ghost ak-source-trigger" aria-haspopup="dialog"
                onClick={() => setSettingsOpen(true)}>切换本体库/数据源</button>
            )}
          </nav>
        </aside>

        <section className="ak-thread" data-agentkit-thread aria-label="对话">
          {assistant ? (
            <div className="ak-assistant-head">
              {view === "board" ? (
                <button type="button" className="ak-ghost" onClick={() => postHost({source: "cockpit-assistant", type: "request", request: "home"})}>返回主页</button>
              ) : (
                <button type="button" className="ak-ghost" onClick={() => postHost({source: "cockpit-assistant", type: "request", request: "board"})}>显示对话看板</button>
              )}
              <button type="button" className="ak-ghost" aria-label="收起助手"
                onClick={() => postHost({source: "cockpit-assistant", type: "request", request: "close"})}>收起</button>
            </div>
          ) : null}
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
            mode={runtimeMode}
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
          <Composer key={`composer:${sessionId}`} busy={blocked} mode={runtimeMode} sessionId={sessionId} assistant={assistant} onSavePreferences={applyPreferences}
            report={report} reportChanging={reportChanging} onAttachments={setAttachments} onUpload={uploadAttachments}
            onWithDb={setReportDatabase} onGenerate={generateReport}
            onPrefillIfEmpty={(value) => {
              if (!runtime.thread.composer.getState().text.trim()) runtime.thread.composer.setText(value);
            }} />
        </section>

        <section className="ak-board" data-agentkit-board aria-label="分析结果">
          <Board turns={workbench.turns} status={workbench.status} onJump={jumpTo}
            onInsight={runtimeMode === "data" || report.with_db ? send : null}
            onPrefill={prefill} busy={blocked} />
        </section>
        <PanelDivider name="调整导航栏宽度" kind="sidebar" value={sidebarWidth} min={176} max={320} onChange={setSidebarWidth} />
        <PanelDivider name="调整对话栏与看板栏宽度" kind="thread" value={threadWidth} min={32} max={48} onChange={setThreadWidth} />
      </div>
      {graphHit ? (
        <OntologyGraph hit={graphHit} sessionId={sessionId} onClose={() => setGraphHit(null)} />
      ) : null}
      {settingsOpen && assistant ? (
        <div className="ak-assistant-info" role="dialog" aria-label="本体库与数据源（只读）">
          <header>
            <h2>本体库与数据源</h2>
            <button type="button" className="ak-ghost" aria-label="关闭本体库与数据源" onClick={() => setSettingsOpen(false)}>关闭</button>
          </header>
          <p>360 全局本体：由客户配置提供，只读。</p>
          <p>团队模型：{assistantModel || "团队模型"}（只读）</p>
          <p>数据源绑定与模型参数写入在客户入口不可用。</p>
        </div>
      ) : null}
      {settingsOpen && !assistant ? (
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
