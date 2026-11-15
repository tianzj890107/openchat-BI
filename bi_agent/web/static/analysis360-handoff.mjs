// 360 智能分析 handoff: the analysis page opened from a cockpit card's 深度分析.
//
// The page is opened as  …/workbench?a360=<handoff id>.  This module makes the
// first chat turn of the page carry that id, so the server turns the session
// into a 360 智能分析 session and starts from the handed-over clause.  The
// visible prompt is the clause's title; the clause context itself stays on
// the server.
import { waitForWorkbench } from "./url-prompt.mjs";

export const HANDOFF_PARAM = "a360";
export const EMBED_PARAM = "embed";
const EMBED_STYLE_ID = "analysis360-embed-style";
// Opened from a cockpit card the page shows the conversation and the board
// only: the navigation rail and its resizer are hidden.
const EMBED_STYLE = [
  "#antd-sidebar-root,#sidebar,#sidebar-resizer,#sidebar-reopen,.layout-resizer-sidebar{display:none!important}",
  ".app-main{flex:1 1 auto!important;width:100%!important;max-width:none!important}",
].join("\n");

export function applyEmbed(document) {
  if (document.getElementById(EMBED_STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = EMBED_STYLE_ID;
  style.textContent = EMBED_STYLE;
  document.head.appendChild(style);
  if (document.body) document.body.dataset.analysis360Embed = "1";
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

export function markMode(document, storage) {
  try { storage.setItem(MODE_KEY, "1"); } catch (_) { /* private mode */ }
  if (document.body) document.body.dataset.analysis360 = "1";
  document.title = "360 智能分析";
}

export async function bootHandoff(window, document) {
  const url = new URL(window.location.href);
  if (url.searchParams.get(EMBED_PARAM) === "1") applyEmbed(document);
  const handoffId = (url.searchParams.get(HANDOFF_PARAM) || "").trim();
  let stored = false;
  try { stored = window.sessionStorage.getItem(MODE_KEY) === "1"; } catch (_) { /* ignore */ }
  if (!handoffId) {
    // A reload of a 360 page keeps its label; the server keeps the session.
    if (stored) markMode(document, window.sessionStorage);
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
  markMode(document, window.sessionStorage);
  window.fetch = withHandoff(window.fetch.bind(window), handoffId);
  const { input, button } = await waitForWorkbench(window, document);
  input.value = handoff.prompt || "深度分析";
  input.dispatchEvent(new window.Event("input", { bubbles: true }));
  button.click();
  return true;
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  void bootHandoff(window, document).catch((error) => console.error("360 analysis handoff failed", error));
}
