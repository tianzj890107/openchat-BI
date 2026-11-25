// HTTP transport for the AgentKit workbench.
//
// The page is served from the analysis app root, so every browser-facing URL
// goes through one APP_ROOT_PATH helper (same contract as the Pro UI workbench).
// Chat turns are SSE frames: one JSON object per `data:` line.

export function withBasePath(path) {
  const appRoot = typeof window !== "undefined" ? window.APP_ROOT_PATH : "";
  const base = String(appRoot || "").replace(/\/+$/, "");
  const clean = String(path || "").replace(/^\/+/, "");
  if (!clean) return base || "/";
  return base ? `${base}/${clean}` : `/${clean}`;
}

async function asJson(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

export async function requestJson(path, {method = "GET", body, signal} = {}) {
  const multipart = typeof FormData !== "undefined" && body instanceof FormData;
  const response = await fetch(withBasePath(path), {
    method,
    cache: "no-store",
    signal,
    ...(multipart ? {body} : body === undefined ? {} : {
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    }),
  });
  const payload = await asJson(response);
  if (!response.ok) {
    const detail = payload?.detail || payload?.message;
    throw new Error(typeof detail === "string" ? detail : `HTTP ${response.status}`);
  }
  return payload;
}

export function loadSources(sessionId, signal) {
  return requestJson(`api/sources?session_id=${encodeURIComponent(sessionId)}`, {signal});
}

export function updateSources(sessionId, body, signal) {
  return requestJson("api/sources", {method: "PUT", body: {...body, session_id: sessionId}, signal});
}

export function loadModelConfig(signal) {
  return requestJson("api/config", {signal});
}

export function updateModelConfig(body) {
  return requestJson("api/config", {method: "PUT", body});
}

export async function listConversations(mode) {
  const payload = await requestJson(`api/conversations${mode ? `?mode=${encodeURIComponent(mode)}` : ""}`);
  return Array.isArray(payload.conversations) ? payload.conversations : [];
}

/**
 * Reopen a stored conversation in the caller's session.
 *
 * The session id is sent explicitly so the restore lands where follow-up
 * questions will be asked; the backend echoes it back. The response carries
 * both the text messages and the AgentKit snapshot (boards/evidence/hits).
 */
export async function openConversation(cid, sessionId = "") {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
  const payload = await requestJson(`api/conversations/${encodeURIComponent(cid)}/activate${query}`, {
    method: "POST",
    body: {},
  });
  return {
    sessionId: payload.session_id || sessionId || "",
    mode: payload.mode || "data",
    messages: Array.isArray(payload.messages) ? payload.messages : [],
    agentkit: payload.agentkit && typeof payload.agentkit === "object" ? payload.agentkit : null,
    sourceRestoreError: payload.source_restore_error || "",
    reportRestoreError: payload.report_restore_error || "",
    awaitingChoice: Boolean(payload.awaiting_choice),
  };
}

export function historyAssets(cid) {
  return requestJson(`api/conversations/${encodeURIComponent(cid)}/assets`);
}

export function loadTrash() {
  return requestJson("api/conversations/trash");
}

export function changeTrash(action, cid) {
  const key = encodeURIComponent(cid || "");
  if (action === "remove") return requestJson(`api/conversations/${key}`, {method: "DELETE"});
  if (action === "restore") return requestJson(`api/conversations/trash/${key}/restore`, {method: "POST"});
  if (action === "purge") return requestJson(`api/conversations/trash/${key}`, {method: "DELETE"});
  if (action === "empty") return requestJson("api/conversations/trash?confirm=1", {method: "DELETE"});
  throw new Error("未知回收站操作");
}

export function reportStatus(sessionId, signal) {
  return requestJson(`api/report/status?session_id=${encodeURIComponent(sessionId)}`, {signal});
}

export function listReports() {
  return requestJson("api/report/list");
}

export function uploadReport(file) {
  const body = new FormData();
  body.append("file", file);
  return requestJson("api/report/upload", {method: "POST", body});
}

export function activateReports(sessionId, ids, withDb, resumeId = "") {
  return requestJson("api/report/activate", {method: "POST", body: {
    session_id: sessionId, report_ids: ids, with_db: withDb, preserve_context: true, resume_conversation_id: resumeId || undefined,
  }});
}

export function startReportGenerator(sessionId) {
  return requestJson(`api/report/generate?session_id=${encodeURIComponent(sessionId)}`, {method: "POST"});
}

export function updateReportConfig(sessionId, withDb) {
  return requestJson("api/report/config", {method: "PUT", body: {session_id: sessionId, with_db: withDb}});
}

/** Persist the current turns so the conversation can be reopened later. */
export async function saveConversation({sessionId, cid, title, turns, handoff, mode = "data", generation, pendingChoice}) {
  const payload = await requestJson("api/conversations/save", {
    method: "POST",
    body: {
      mode,
      session_id: sessionId || "",
      cid: cid || undefined,
      title: title || "",
      first_user_question: title || "",
      generation,
      agentkit: {
        version: 1,
        turns: turns || [],
        ...(handoff ? {handoff} : {}),
        ...(pendingChoice ? {pendingChoice} : {}),
      },
    },
  });
  return {cid: payload.id || cid || ""};
}

/** Read one SSE response and dispatch every JSON frame to `onEvent`. */
async function readEventStream(response, onEvent) {
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => "");
    let message = text || `HTTP ${response.status}`;
    try {
      const body = JSON.parse(text);
      message = body?.error?.message || body?.message || message;
      if (body?.error?.code) message = `${body.error.code}: ${message}`;
    } catch {
      /* plain text error */
    }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let terminal = false;
  let waiting = false;
  const dispatch = (line) => {
    if (!line.startsWith("data:")) return;
    let event;
    try { event = JSON.parse(line.slice(5).trim()); } catch { return; }
    if (["done", "error", "session_superseded", "stream_interrupted"].includes(event.type)) terminal = true;
    if (["user_choice_requested", "awaiting_user_choice"].includes(event.type)) waiting = true;
    if (event.type === "user_choice_resolved") waiting = false;
    onEvent(event);
  };
  let buffer = "";
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const frames = buffer.split(/\r?\n/);
    buffer = frames.pop() || "";
    for (const line of frames) dispatch(line);
  }
  dispatch((buffer + decoder.decode()).trim());
  if (!terminal && !waiting) onEvent({type: "stream_interrupted", message: "响应中断，已保留部分结果。"});
}


/** Chat request body: visible question + optional card scope. */
export function buildChatBody({message, visibleText, sessionId, scope}) {
  const body = {
    message,
    visible_user_text: visibleText ?? message,
    session_id: sessionId || "",
  };
  if (scope && scope.anchor) body.scope = scope;
  return body;
}

/** Ask one question; resolves when the turn's stream ends. */
export async function streamChat({message, visibleText, sessionId, scope, signal, onEvent, mode = "data"}) {
  const response = await fetch(withBasePath(mode === "report" ? "api/report/chat" : "api/chat"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(buildChatBody({message, visibleText, sessionId, scope: mode === "data" ? scope : null})),
    signal,
  });
  await readEventStream(response, onEvent);
}

/** Resume a turn that paused on a clarification card. */
export async function chooseOption({sessionId, ids, labels, signal, onEvent, mode = "data"}) {
  const response = await fetch(withBasePath(mode === "report" ? "api/report/choice" : "api/choice"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      session_id: sessionId || "",
      choice_ids: ids,
      choice_labels: labels,
    }),
    signal,
  });
  await readEventStream(response, onEvent);
}

/** Ontology context/expand subgraph for one hit (read-only). */
export function fetchSubgraph(request, signal) {
  return requestJson("api/ontology/subgraph", {method: "POST", body: request, signal});
}
