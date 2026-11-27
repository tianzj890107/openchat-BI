// 储小策智能助手: the Ontology Analyst workbench embedded in the cockpit
// (…/workbench?a360=assistant).  The cockpit docks this page on the left of
// its 360 看板 and asks it for one of two views:
//
//   chat  — only the conversation column; the cockpit's home board stays on
//           the right.
//   board — the conversation column plus this conversation's own 看板, filling
//           the cockpit window.
//
// The page sends the cockpit two requests back: 显示对话看板 (chat header) asks
// for the board view, 返回主页 (dashboard header) for the home board, and ‹
// collapses the assistant.  The workbench sidebar is hidden; its history and
// 新对话 move to a 历史对话 dropdown next to the composer's model chip.
//
// Everything here works on the workbench's DOM (the runtime's legacy
// #recent-list keeps the click handlers that restore a conversation), so the
// React bundle is unchanged.

export const MESSAGE_SOURCE = "cockpit-assistant";
export const VIEWS = Object.freeze(["chat", "board"]);
export const REQUESTS = Object.freeze(["board", "home", "close"]);
export const VIEW_ATTR = "a360View";

export function viewMessage(view) {
  return { source: MESSAGE_SOURCE, type: "view", view: VIEWS.includes(view) ? view : "chat" };
}

export function requestMessage(request) {
  return { source: MESSAGE_SOURCE, type: "request", request };
}

// A message is only accepted from the same origin and only in the known shape.
export function readMessage(event, origin, type) {
  if (!event || event.origin !== origin) return null;
  const data = event.data;
  if (!data || typeof data !== "object" || data.source !== MESSAGE_SOURCE || data.type !== type) return null;
  if (type === "view") return VIEWS.includes(data.view) ? data.view : null;
  if (type === "request") return REQUESTS.includes(data.request) ? data.request : null;
  return null;
}

export function setView(document, view) {
  const next = VIEWS.includes(view) ? view : "chat";
  document.documentElement.dataset[VIEW_ATTR] = next;
  return next;
}

const HISTORY_ID = "a360-assistant-history";
const POPOVER_ID = "a360-assistant-history-pop";

function el(document, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function headerButton(document, action, label, title) {
  const button = el(document, "button", "a360-assistant-btn", label);
  button.type = "button";
  button.dataset.a360Action = action;
  button.title = title || label;
  button.setAttribute("aria-label", title || label);
  return button;
}

// The welcome for an empty conversation: 储小策，我帮你 / 看目标 · 看差距 · 看趋势.
function mountBrand(document) {
  const layer = document.getElementById("pro-ui-empty-layer");
  if (!layer || layer.querySelector(".a360-assistant-brand")) return;
  const brand = el(document, "div", "a360-assistant-brand");
  const title = el(document, "h1", "a360-assistant-brand__title", "储小策，");
  title.appendChild(el(document, "span", "a360-assistant-brand__highlight", "我帮你"));
  brand.append(title, el(document, "p", "a360-assistant-brand__subtitle", "看目标 · 看差距 · 看趋势"));
  layer.prepend(brand);
}

function mountChatHeader(document, send) {
  const header = document.querySelector(".chat-pane > .pane-header");
  if (!header || header.querySelector(".a360-assistant-actions")) return;
  const label = document.getElementById("pane-label");
  if (label) label.textContent = "储小策";
  const actions = el(document, "div", "a360-assistant-actions");
  const showBoard = headerButton(document, "board", "显示对话看板", "在右侧显示当前对话的看板");
  showBoard.classList.add("a360-assistant-btn--primary", "a360-assistant-show-board");
  const collapse = headerButton(document, "close", "‹", "收起储小策智能助手");
  collapse.classList.add("a360-assistant-btn--icon");
  showBoard.addEventListener("click", () => send("board"));
  collapse.addEventListener("click", () => send("close"));
  actions.append(showBoard, collapse);
  header.appendChild(actions);
}

function mountBoardHeader(document, send) {
  const header = document.querySelector(".dashboard-pane > .pane-header");
  if (!header || header.querySelector(".a360-assistant-home")) return;
  const home = headerButton(document, "home", "返回主页", "右侧返回驾驶舱主页看板");
  home.classList.add("a360-assistant-home");
  home.insertAdjacentHTML("afterbegin",
    '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M2.5 7.2 8 2.8l5.5 4.4M4 6.2V13h3v-3.2h2V13h3V6.2" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>');
  home.addEventListener("click", () => send("home"));
  header.appendChild(home);
}

// 历史对话: a dropdown right of the model chip (团队 API …) listing the
// runtime's recent conversations, plus 新对话.
function mountHistory(window, document) {
  const tools = document.querySelector(".pro-ui-composer-tools");
  if (!tools || tools.querySelector("#" + HISTORY_ID)) return;
  const chip = tools.querySelector(".pro-ui-model-chip");
  const button = el(document, "button", "a360-assistant-history");
  button.type = "button";
  button.id = HISTORY_ID;
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", POPOVER_ID);
  button.title = "历史对话";
  button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><circle cx="8" cy="8" r="5.8" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M8 4.8V8l2.2 1.4" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg><span>历史对话</span><i aria-hidden="true">▾</i>';
  if (chip && chip.parentNode === tools) chip.after(button);
  else tools.prepend(button);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleHistory(window, document, button);
  });
}

function closeHistory(document) {
  const pop = document.getElementById(POPOVER_ID);
  if (pop) pop.hidden = true;
  const button = document.getElementById(HISTORY_ID);
  if (button) {
    button.setAttribute("aria-expanded", "false");
    button.classList.remove("is-open");
  }
}

function renderHistory(document, pop) {
  const list = pop.querySelector(".a360-assistant-pop__list");
  list.textContent = "";
  const source = document.getElementById("recent-list");
  const rows = source ? [...source.querySelectorAll(".recent-item")] : [];
  if (!rows.length) {
    const status = source && source.dataset.status;
    list.appendChild(el(document, "div", "a360-assistant-pop__empty",
      status === "loading" ? "正在加载历史对话…" : status === "error" ? "历史对话加载失败" : "暂无历史对话"));
    return;
  }
  rows.forEach((row) => {
    const item = el(document, "button", "a360-assistant-pop__item" + (row.classList.contains("active") ? " is-active" : ""),
      row.title || row.textContent.trim() || "未命名对话");
    item.type = "button";
    item.setAttribute("role", "menuitem");
    item.title = row.title || "";
    item.addEventListener("click", () => {
      closeHistory(document);
      row.click();
    });
    list.appendChild(item);
  });
}

function toggleHistory(window, document, button) {
  let pop = document.getElementById(POPOVER_ID);
  if (pop && !pop.hidden) {
    closeHistory(document);
    return;
  }
  if (!pop) {
    pop = el(document, "div", "a360-assistant-pop");
    pop.id = POPOVER_ID;
    pop.setAttribute("role", "menu");
    pop.setAttribute("aria-label", "历史对话");
    const head = el(document, "div", "a360-assistant-pop__head");
    head.appendChild(el(document, "strong", "", "历史对话"));
    const fresh = el(document, "button", "a360-assistant-pop__new", "＋ 新对话");
    fresh.type = "button";
    fresh.addEventListener("click", () => {
      closeHistory(document);
      document.getElementById("nav-new-chat")?.click();
    });
    head.appendChild(fresh);
    pop.append(head, el(document, "div", "a360-assistant-pop__list"));
    pop.addEventListener("click", (event) => event.stopPropagation());
    document.body.appendChild(pop);
  }
  renderHistory(document, pop);
  pop.hidden = false;
  const rect = button.getBoundingClientRect();
  const width = Math.min(320, window.innerWidth - 16);
  pop.style.width = width + "px";
  pop.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)) + "px";
  pop.style.bottom = Math.max(8, window.innerHeight - rect.top + 6) + "px";
  button.setAttribute("aria-expanded", "true");
  button.classList.add("is-open");
}

export function mountAssistantMode(window, document) {
  const root = document.documentElement;
  root.dataset.analysis360Assistant = "1";
  setView(document, new URL(window.location.href).searchParams.get("view") || "chat");
  const parent = window.parent && window.parent !== window ? window.parent : null;
  const origin = window.location.origin;
  const send = (request) => {
    if (parent) parent.postMessage(requestMessage(request), origin);
    // Opened on its own: 显示对话看板 / 返回主页 still switch this page.
    else if (request === "board" || request === "home") setView(document, request === "board" ? "board" : "chat");
  };

  window.addEventListener("message", (event) => {
    const view = readMessage(event, origin, "view");
    if (!view) return;
    setView(document, view);
    closeHistory(document);
    window.dispatchEvent(new window.Event("resize"));
  });

  const mount = () => {
    mountBrand(document);
    mountChatHeader(document, send);
    mountBoardHeader(document, send);
    mountHistory(window, document);
  };
  // The React composer and welcome mount after this module; keep the pieces
  // in place when they (re)render.
  let frame = 0;
  const observer = new window.MutationObserver(() => {
    if (frame) return;
    frame = window.requestAnimationFrame(() => { frame = 0; mount(); });
  });
  const start = () => {
    mount();
    observer.observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start, { once: true });

  document.addEventListener("click", () => closeHistory(document));
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeHistory(document); });
  window.addEventListener("resize", () => closeHistory(document));
  if (parent) parent.postMessage({ source: MESSAGE_SOURCE, type: "ready" }, origin);
  return { send };
}
