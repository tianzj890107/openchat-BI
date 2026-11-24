// HTTP transport for the AgentKit workbench.
//
// The page is served from the analysis app root, so every browser-facing URL
// goes through one APP_ROOT_PATH helper (same contract as the Pro UI workbench).
// Chat turns are SSE frames: one JSON object per `data:` line.

export function withBasePath(path) {
  const base = String(window.APP_ROOT_PATH || "").replace(/\/+$/, "");
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

/** Reopen a stored conversation and return its server session + messages. */
export async function openConversation(cid) {
  const response = await fetch(
    withBasePath(`api/conversations/${encodeURIComponent(cid)}/activate`),
    {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"},
  );
  const payload = await asJson(response);
  let messages = Array.isArray(payload.messages) ? payload.messages : [];
  if (!messages.length) {
    const record = await fetch(
      withBasePath(`api/conversations/${encodeURIComponent(cid)}/record`),
      {cache: "no-store"},
    );
    const stored = await asJson(record);
    const conversation = stored.conversation || {};
    if (Array.isArray(conversation.messages)) messages = conversation.messages;
  }
  return {sessionId: payload.session_id || "", messages};
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

/** Ask one question; resolves when the turn's stream ends. */
export async function streamChat({message, sessionId, signal, onEvent}) {
  const response = await fetch(withBasePath("api/chat"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({message, visible_user_text: message, session_id: sessionId || ""}),
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
