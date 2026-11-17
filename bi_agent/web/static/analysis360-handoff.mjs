// 360 智能分析 handoff: the analysis page opened from a cockpit card's 深度分析.
//
// The page is opened as  …/workbench?a360=<handoff id>.  This module makes the
// first chat turn of the page carry that id, so the server turns the session
// into a 360 智能分析 session and starts from the handed-over clause.  The
// visible prompt is the clause's title; the clause context itself stays on
// the server.
import { waitForWorkbench } from "./url-prompt.mjs";

export const HANDOFF_PARAM = "a360";

// The workbench page auto-sends the handed-over clause (the old behaviour).
// The cockpit embed passes send=0 and waits for the user to press the button.
export function handoffSendMode(search) {
  try {
    return new URLSearchParams(String(search ?? "")).get("send") === "0" ? "manual" : "auto";
  } catch (_) {
    return "auto";
  }
}
export const HANDOFF_FIELD = "analysis360_handoff";
const MODE_KEY = "eimosp-analysis360-mode";

export function isChatRequest(input, init) {
  const url = typeof input === "string" ? input : (input && input.url) || "";
  const method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
  if (method !== "POST") return false;
  try {
    return new URL(url, "http://local/").pathname.endsWith("/api/chat");
  } catch (_) {
    return false;
  }
}

// Add the handoff id to the next chat request, exactly once.
export function withHandoff(fetchImpl, handoffId) {
  let pending = handoffId;
  return function fetchWithHandoff(input, init) {
    if (pending && isChatRequest(input, init) && init && typeof init.body === "string") {
      try {
        const body = JSON.parse(init.body);
        body[HANDOFF_FIELD] = pending;
        pending = "";
        return fetchImpl(input, { ...init, body: JSON.stringify(body) });
      } catch (_) {
        // Not a JSON body: leave the request untouched.
      }
    }
    return fetchImpl(input, init);
  };
}

// The customer delivery does not expose the general `/api/chat` surface.  The
// 360 workbench keeps the normal runtime, but its chat and AskUser choice calls
// go through dedicated endpoints that refuse sessions without a 360 run.
export function analysis360ApiPath(url, method) {
  if (String(method || "GET").toUpperCase() !== "POST") return url;
  const text = typeof url === "string" ? url : (url && url.url) || "";
  let parsed;
  try { parsed = new URL(text, "http://analysis360.local"); } catch (_) { return url; }
  let suffix = "";
  if (parsed.pathname.endsWith("/api/chat")) suffix = "/api/chat";
  else if (parsed.pathname.endsWith("/api/choice")) suffix = "/api/choice";
  if (!suffix) return url;
  parsed.pathname = parsed.pathname.slice(0, -suffix.length) + "/api/analysis360" + suffix.slice(4);
  if (/^[a-z]+:\/\//i.test(text)) return parsed.href;
  return parsed.pathname + parsed.search + parsed.hash;
}

export function withAnalysis360Routes(fetchImpl) {
  return function fetchForAnalysis360(input, init) {
    const method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    const rewritten = analysis360ApiPath(input, method);
    return fetchImpl(rewritten, init);
  };
}

export function markMode(document, storage) {
  try { storage.setItem(MODE_KEY, "1"); } catch (_) { /* private mode */ }
  if (document.documentElement) document.documentElement.dataset.analysis360 = "1";
  if (document.body) document.body.dataset.analysis360 = "1";
  document.title = "360 智能分析";
}

export async function bootHandoff(window, document) {
  const url = new URL(window.location.href);
  const handoffId = (url.searchParams.get(HANDOFF_PARAM) || "").trim();
  let stored = false;
  try { stored = window.sessionStorage.getItem(MODE_KEY) === "1"; } catch (_) { /* ignore */ }
  if (handoffId || stored) markMode(document, window.sessionStorage);
  if (!handoffId) {
    // A reload of a 360 page keeps its label; the server keeps the session.
    if (stored) window.fetch = withAnalysis360Routes(window.fetch.bind(window));
    return false;
  }
  // Consume the parameter first so a refresh cannot repeat the handoff.
  url.searchParams.delete(HANDOFF_PARAM);
  window.history.replaceState(window.history.state, "", url.href);
  const response = await window.fetch(
    new URL(`../api/analysis360/handoff/${encodeURIComponent(handoffId)}`, import.meta.url));
  if (!response.ok) {
    window.alert("深度分析交接已失效，请回到卡片重新点击“深度分析”。");
    return false;
  }
  const handoff = await response.json();
  window.fetch = withHandoff(withAnalysis360Routes(window.fetch.bind(window)), handoffId);
  const { input, button } = await waitForWorkbench(window, document);
  input.value = handoff.prompt || "深度分析";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  if (handoffSendMode(url.search) === "auto") button.click();
  return true;
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  void bootHandoff(window, document).catch((error) => console.error("360 analysis handoff failed", error));
}
