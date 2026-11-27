// 储小策智能助手 ⇄ 驾驶舱的 iframe 消息合同（与 cockpit/assistant.js 共用）。
// 嵌入页与宿主同源；每条消息都校验 origin、source window、source 字段和枚举值。

export const MESSAGE_SOURCE = 'cockpit-assistant';
export const ASSISTANT_PATH = '/workbench?a360=assistant';
export const ASSISTANT_VIEWS = Object.freeze(['chat', 'board']);
export const SESSION_KEY = 'chuxiaoce.assistant.session';

export function isAssistant(search) {
  return new URLSearchParams(search || '').get('a360') === 'assistant';
}

export function initialView(search) {
  return new URLSearchParams(search || '').get('view') === 'board' ? 'board' : 'chat';
}

export function assistantUrl(root, view) {
  const base = String(root || '').replace(/\/+$/, '');
  const current = view === 'board' ? 'board' : 'chat';
  return `${base}${ASSISTANT_PATH}&view=${current}`;
}

export function viewMessage(view) {
  return {source: MESSAGE_SOURCE, type: 'view', view: view === 'board' ? 'board' : 'chat'};
}

export function requestMessage(request) {
  return {source: MESSAGE_SOURCE, type: 'request', request};
}

function envelope(event, origin, sourceWindow) {
  if (!event || event.origin !== origin) return null;
  if (!sourceWindow || event.source !== sourceWindow) return null;
  const data = event.data;
  if (!data || typeof data !== 'object' || data.source !== MESSAGE_SOURCE) return null;
  return data;
}

export function readHostView(event, origin, sourceWindow) {
  const data = envelope(event, origin, sourceWindow);
  if (!data || data.type !== 'view') return null;
  return ASSISTANT_VIEWS.includes(data.view) ? data.view : null;
}

export function isReady(event, origin, sourceWindow) {
  const data = envelope(event, origin, sourceWindow);
  return Boolean(data && data.type === 'ready');
}

export function readCurrentSession(storage) {
  try {
    return storage?.getItem(SESSION_KEY) || '';
  } catch {
    return '';
  }
}

export function rememberSession(storage, sessionId) {
  try {
    if (sessionId) storage?.setItem(SESSION_KEY, sessionId);
  } catch { /* restricted storage */ }
}

export function resumeSession(storage, makeId) {
  const existing = readCurrentSession(storage);
  if (existing) return existing;
  const created = makeId();
  rememberSession(storage, created);
  return created;
}

const SNAPSHOT_PREFIX = "chuxiaoce.assistant.snapshot.";

export function readSnapshot(sessionId, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(SNAPSHOT_PREFIX + sessionId);
    const value = raw ? JSON.parse(raw) : null;
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

export function writeSnapshot(sessionId, value, storage = globalThis.localStorage) {
  try {
    if (sessionId) storage?.setItem(SNAPSHOT_PREFIX + sessionId, JSON.stringify(value));
  } catch { /* restricted storage */ }
}

export function removeSnapshot(sessionId, storage = globalThis.localStorage) {
  try {
    if (sessionId) storage?.removeItem(SNAPSHOT_PREFIX + sessionId);
  } catch { /* restricted storage */ }
}
