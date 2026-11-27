// 储小策智能助手: a button at the cockpit's bottom-right that docks the
// Ontology Analyst conversation (…/workbench?a360=assistant, 360 智能分析) on
// the left of the cockpit's 360 看板.
//
//   board — opening the assistant shows the conversation and, in place of the
//           cockpit board, the conversation's own 看板.  Its 返回主页 button
//           brings the cockpit board back.
//   home  — the conversation stays docked on the left of the cockpit board;
//           显示对话看板 at the top-right of the conversation calls the
//           conversation's 看板 again.
//
// The workbench and the cockpit talk through same-origin postMessage; the
// message shape matches static/analysis360-assistant.mjs (kept inline here
// because the static cockpit site ships only static/cockpit).  The frame is
// created on the first open and kept while the assistant is collapsed, so a
// running conversation is not lost.

export const MESSAGE_SOURCE = 'cockpit-assistant';
const REQUESTS = ['board', 'home', 'close'];

export function viewMessage(view) {
  return {source: MESSAGE_SOURCE, type: 'view', view: view === 'board' ? 'board' : 'chat'};
}

// A request from the workbench frame: 显示对话看板 (board), 返回主页 (home) or
// ‹ (close).  Only the same origin and the known shape are accepted.
export function readRequest(event, origin) {
  if (!event || event.origin !== origin) return null;
  const data = event.data;
  if (!data || typeof data !== 'object' || data.source !== MESSAGE_SOURCE || data.type !== 'request') return null;
  return REQUESTS.includes(data.request) ? data.request : null;
}

export const ASSISTANT_PATH = '/workbench-agentkit?a360=assistant';
export const ASSISTANT_NAME = '储小策智能助手';
export const VIEWS = Object.freeze(['closed', 'home', 'board']);

export function assistantUrl(root, view) {
  return `${String(root || '').replace(/\/+$/, '')}${ASSISTANT_PATH}&view=${view === 'board' ? 'board' : 'chat'}`;
}

// The child announces readiness so the host can push its current view even
// when the frame loads after the first postMessage.
export function isReady(event, origin, sourceWindow) {
  if (!event || event.origin !== origin) return false;
  if (!sourceWindow || event.source !== sourceWindow) return false;
  const data = event.data;
  return Boolean(data && data.source === MESSAGE_SOURCE && data.type === 'ready');
}

// The cockpit view → the workbench view (home shows the conversation only).
export function workbenchView(view) {
  return view === 'board' ? 'board' : 'chat';
}

export function mountAssistant(doc = document, win = window) {
  if (!doc.body || doc.getElementById('cockpit-assistant-fab')) return null;
  const meta = doc.querySelector('meta[name="app-root"]');
  const root = meta ? meta.getAttribute('content') || '' : '';
  const url = assistantUrl(root.startsWith('@@') ? '' : root);
  const origin = win.location.origin;

  const fab = doc.createElement('button');
  fab.type = 'button';
  fab.id = 'cockpit-assistant-fab';
  fab.className = 'cockpit-assistant-fab';
  fab.setAttribute('aria-expanded', 'false');
  fab.setAttribute('aria-controls', 'cockpit-assistant-panel');
  fab.title = `打开${ASSISTANT_NAME}`;
  fab.innerHTML = '<span class="cockpit-assistant-fab__icon" aria-hidden="true">AI</span><span>储小策智能助手</span>';

  const panel = doc.createElement('section');
  panel.id = 'cockpit-assistant-panel';
  panel.className = 'cockpit-assistant';
  panel.setAttribute('aria-label', ASSISTANT_NAME);
  panel.hidden = true;

  let frame = null;
  let view = 'closed';

  function post() {
    if (frame && frame.contentWindow && view !== 'closed') {
      frame.contentWindow.postMessage(viewMessage(workbenchView(view)), origin);
    }
  }
  function setView(next) {
    view = VIEWS.includes(next) ? next : 'closed';
    const open = view !== 'closed';
    if (open && !frame) {
      frame = doc.createElement('iframe');
      frame.className = 'cockpit-assistant__frame';
      frame.title = ASSISTANT_NAME;
      frame.setAttribute('allow', 'clipboard-write');
      frame.src = assistantUrl(root, workbenchView(view));
      panel.appendChild(frame);
    }
    panel.hidden = !open;
    panel.dataset.view = view;
    doc.documentElement.classList.toggle('cockpit-assistant-docked', open);
    doc.documentElement.dataset.cockpitAssistant = view;
    fab.setAttribute('aria-expanded', String(open));
    fab.classList.toggle('is-open', open);
    fab.title = open ? `收起${ASSISTANT_NAME}` : `打开${ASSISTANT_NAME}`;
    post();
    // The cockpit charts follow their new width.
    win.requestAnimationFrame(() => win.dispatchEvent(new win.Event('resize')));
  }
  const open = () => setView('board');
  const close = () => {
    setView('closed');
    fab.focus();
  };

  fab.addEventListener('click', () => (view === 'closed' ? open() : close()));
  win.addEventListener('message', event => {
    if (!frame || event.source !== frame.contentWindow) return;
    const data = event.data;
    if (isReady(event, origin, frame.contentWindow)) {
      post();
      return;
    }
    const request = readRequest(event, origin);
    if (request === 'board') setView('board');
    else if (request === 'home') setView('home');
    else if (request === 'close') close();
  });

  doc.body.append(panel, fab);
  return {fab, panel, open, close, setView, url, get view() { return view; }};
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mountAssistant());
  else mountAssistant();
}
