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

export async function listConversations() {
  const response = await fetch(withBasePath("api/conversations"), {cache: "no-store"});
  const payload = await asJson(response);
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
  const response = await fetch(
    withBasePath(`api/conversations/${encodeURIComponent(cid)}/activate${query}`),
    {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"},
  );
  const payload = await asJson(response);
  return {
    sessionId: payload.session_id || sessionId || "",
    messages: Array.isArray(payload.messages) ? payload.messages : [],
    agentkit: payload.agentkit && typeof payload.agentkit === "object" ? payload.agentkit : null,
  };
}

/** Persist the current turns so the conversation can be reopened later. */
export async function saveConversation({sessionId, cid, title, turns, handoff}) {
  const response = await fetch(withBasePath("api/conversations/save"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      mode: "data",
      session_id: sessionId || "",
      cid: cid || undefined,
      title: title || "",
      first_user_question: title || "",
      agentkit: {
        version: 1,
        turns: turns || [],
        ...(handoff ? {handoff} : {}),
      },
    }),
  });
  const payload = await asJson(response);
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
  let buffer = "";
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, {stream: true});
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload));
        } catch {
          /* ignore malformed frame, keep the stream alive */
        }
      }
    }
  }
  const tail = buffer.trim();
  if (tail.startsWith("data:")) {
    try {
      onEvent(JSON.parse(tail.slice(5).trim()));
    } catch {
      /* ignore trailing partial frame */
    }
  }
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
export async function streamChat({message, sessionId, scope, signal, onEvent}) {
  const response = await fetch(withBasePath("api/chat"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(buildChatBody({message, sessionId, scope})),
    signal,
  });
  await readEventStream(response, onEvent);
}

/** Resume a turn that paused on a clarification card. */
export async function chooseOption({sessionId, ids, labels, signal, onEvent}) {
  const response = await fetch(withBasePath("api/choice"), {
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
export async function fetchSubgraph(request, signal) {
  const response = await fetch(withBasePath("api/ontology/subgraph"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(request),
    signal,
  });
  const payload = await asJson(response);
  if (!response.ok) {
    throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`);
  }
  return payload;
}
