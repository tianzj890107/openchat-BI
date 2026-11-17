// Real Vue mount tests for the 根因深度分析 dialog.
//
// The cockpit ships the Vue global build (vendor/vue.global.prod.js) and no DOM
// library, so the tests mount the real component through Vue's custom renderer
// into a tiny element tree.  That keeps the assertions on rendered output,
// events and requests instead of source-string matching.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const VUE_SOURCE = new URL('../bi_agent/web/static/cockpit/vendor/vue.global.prod.js', import.meta.url);
const read = path => readFile(new URL(path, import.meta.url), 'utf8');

let vuePromise = null;
async function loadVue() {
  if (!vuePromise) {
    vuePromise = (async () => {
      const code = await readFile(VUE_SOURCE, 'utf8');
      // The prod compiler decodes attribute values through a detached element.
      // Without a working decoder every `v-if="a && b"` would look empty.
      const decoder = () => {
        const el = {_html: ''};
        Object.defineProperty(el, 'innerHTML', {
          get: () => el._html,
          set: value => { el._html = String(value); },
        });
        Object.defineProperty(el, 'textContent', {
          get: () => el._html.replace(/&lt;/g, '<').replace(/&gt;/g, '>')
            .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&'),
          set: value => { el._html = String(value); },
        });
        el.children = [{ getAttribute: () => {
          const match = el._html.match(/foo="([\s\S]*)"\s*>$/);
          return match ? match[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&') : '';
        }}];
        return el;
      };
      const sandbox = { console, setTimeout, clearTimeout, queueMicrotask, Promise,
        document: { createElement: decoder, createTextNode: () => ({}) },
        navigator: { userAgent: 'node-test' } };
      sandbox.globalThis = sandbox;
      sandbox.self = sandbox;
      sandbox.window = sandbox;
      vm.createContext(sandbox);
      vm.runInContext(code, sandbox);
      return sandbox.Vue;
    })();
  }
  return vuePromise;
}

function makeNode(tag) {
  const el = {
    nodeType: 1,
    tagName: String(tag).toUpperCase(),
    children: [],
    parentNode: null,
    props: {},
    listeners: {},
    attributes: {},
    className: '',
    value: '',
    innerHTML: '',
    textContent: '',
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    appendChild(child) {
      el.children.push(child);
      child.parentNode = el;
      return child;
    },
    insertBefore(child, anchor) {
      const index = anchor ? el.children.indexOf(anchor) : -1;
      if (index >= 0) el.children.splice(index, 0, child);
      else el.children.push(child);
      child.parentNode = el;
      return child;
    },
    removeChild(child) {
      const index = el.children.indexOf(child);
      if (index >= 0) el.children.splice(index, 1);
      child.parentNode = null;
      return child;
    },
    insert(child, anchor) {
      return anchor ? el.insertBefore(child, anchor) : el.appendChild(child);
    },
    remove() {
      if (el.parentNode) el.parentNode.removeChild(el);
    },
    setAttribute(name, value) { el.attributes[name] = String(value); },
    removeAttribute(name) { delete el.attributes[name]; },
    addEventListener() {},
    removeEventListener() {},
    focus() { el.ownerDocument.activeElement = el; },
    blur() { if (el.ownerDocument.activeElement === el) el.ownerDocument.activeElement = null; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
    get firstChild() { return el.children[0] || null; },
  };
  return el;
}

const FOCUSABLE_SELECTOR = 'button, textarea, input, [tabindex]';

function makeDocument() {
  const doc = {
    activeElement: null,
    createElement: tag => {
      const el = makeNode(tag);
      el.ownerDocument = doc;
      return el;
    },
    createTextNode: text => ({ nodeType: 3, text, parentNode: null }),
    createComment: text => ({ nodeType: 8, text, parentNode: null }),
    getElementById: () => null,
    querySelector: () => null,
    addEventListener() {},
    removeEventListener() {},
  };
  doc.body = doc.createElement('body');
  doc.head = doc.createElement('head');
  return doc;
}

function walk(node, visit) {
  if (!node) return;
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

function findAll(root, predicate) {
  const found = [];
  walk(root, node => { if (predicate(node)) found.push(node); });
  return found;
}

function byClass(root, cls) {
  return findAll(root, node => String(node.className || '').split(/\s+/).includes(cls));
}

function textOf(node) {
  let text = '';
  walk(node, item => {
    if (item.nodeType === 3) text += item.text;
    else if (item.innerHTML) text += item.innerHTML;
    else if (item.textContent) text += item.textContent;
  });
  return text;
}

/** Mount a component with the real Vue runtime into a detached element tree. */
async function mount(component, props = {}, {opener = false} = {}) {
  const Vue = await loadVue();
  const doc = makeDocument();
  const openerEl = opener ? doc.createElement('button') : null;
  if (openerEl) {
    doc.body.appendChild(openerEl);
    doc.activeElement = openerEl;
  }
  const root = doc.createElement('div');
  const body = doc.body;
  body.querySelectorAll = selector => (selector === FOCUSABLE_SELECTOR
    ? findAll(body, node => ['BUTTON', 'TEXTAREA', 'INPUT'].includes(node.tagName)) : []);
  const docWithBody = doc;
  docWithBody.querySelector = selector => (selector === 'body' ? body : null);

  globalThis.window = { Vue, document: doc, crypto: { randomUUID: () => 'session-1' }, fetch: () => { throw new Error('fetch not stubbed'); } };
  globalThis.Vue = Vue;
  globalThis.document = doc;

  const renderer = Vue.createRenderer({
    createElement: tag => doc.createElement(tag),
    createText: text => Object.assign(doc.createTextNode(text), {
      remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    }),
    createComment: text => Object.assign(doc.createComment(text), {
      remove() { if (this.parentNode) this.parentNode.removeChild(this); },
    }),
    setText: (node, text) => { node.text = text; },
    setElementText: (node, text) => { node.children = []; node.innerHTML = ''; node.textContent = text; },
    insert: (child, parent, anchor) => { parent.insert(child, anchor || null); },
    remove: child => {
      if (typeof child.remove === 'function') child.remove();
      else if (child.parentNode) child.parentNode.removeChild(child);
    },
    parentNode: node => node.parentNode,
    nextSibling: node => {
      const parent = node.parentNode;
      if (!parent) return null;
      return parent.children[parent.children.indexOf(node) + 1] || null;
    },
    querySelector: selector => (selector === 'body' ? body : null),
    setScopeId: (el, id) => { el.attributes['data-v'] = id; },
    cloneNode: node => ({ ...node }),
    insertStaticContent: (content, parent, anchor) => {
      const el = doc.createElement('div');
      el.innerHTML = String(content);
      parent.insert(el, anchor || null);
      return [el, el];
    },
    patchProp: (el, key, previous, next) => {
      if (!el) return;
      if (key === 'class') el.className = next || '';
      else if (key === 'value' || key === 'modelValue') el.value = next;
      else if (key === 'innerHTML') el.innerHTML = next || '';
      else if (key === 'textContent') el.textContent = next || '';
      else if (key.startsWith('on') && typeof next === 'function') el.listeners[key.toLowerCase()] = next;
      else el.props[key] = next;
    },
  });
  // Compile without static hoisting: the fake element tree cannot host the
  // hoisted HTML strings, and the assertions only need the live vnodes.
  if (component && component.template && !component.render) {
    component.render = Vue.compile(component.template, { hoistStatic: false });
  }
  const app = renderer.createApp({ render: () => Vue.h(component, props) });
  app.mount(root);
  return { app, doc, root, body, opener: openerEl, get tree() { return body.children.length ? body : root; }, Vue };
}

function trigger(node, event) {
  const handler = node && node.listeners[`on${event}`];
  if (typeof handler === 'function') handler({ type: event, preventDefault() {}, stopPropagation() {}, isComposing: false });
}

function sseResponse(events, { chunkSize = 7 } = {}) {
  const payload = events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('');
  const bytes = new TextEncoder().encode(payload);
  let offset = 0;
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    body: {
      getReader() {
        return {
          async read() {
            if (offset >= bytes.length) return { done: true, value: undefined };
            const next = bytes.slice(offset, offset + chunkSize);
            offset += chunkSize;
            return { done: false, value: next };
          },
          async cancel() {},
        };
      },
    },
  };
}

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body, body: null };
}

const CAUSE = {
  id: 'cause-1', title: '供应链交期延迟', description: '交期超过 12 天，影响 3 条商机',
  stageLabel: '商机获取', inferred: true,
};
const PAYLOAD = {
  kind: 'cause',
  clause: { code: 'RC09', title: '供应链交期延迟', description: '交期超过 12 天', level: '', status: '',
    decidedBy: 'rule', metricCodes: [], linkedRisks: ['RK02'], inferred: true },
  period: '2025-10', measurementDate: '2025-10-31',
  card: { stage: '商机获取', title: '商机获取', ontology: 'V3', slot: 'opportunity-risk' },
  siblings: [], facts: [],
};

async function loadDialog() {
  const Vue = await loadVue();
  const doc = makeDocument();
  globalThis.window = { Vue, document: doc, crypto: { randomUUID: () => 'session-1' }, fetch: () => { throw new Error('fetch not stubbed'); } };
  globalThis.Vue = Vue;
  globalThis.document = doc;
  return import(`../bi_agent/web/static/cockpit/insight-components/deep-analysis/dialog.js?ui=${Math.random()}`);
}

test('the cockpit card registers the dialog component (it must not render a bare tag)', async () => {
  const Vue = await loadVue();
  globalThis.window = { Vue };
  globalThis.Vue = Vue;
  globalThis.document = makeDocument();
  globalThis.location = { pathname: '/app/cockpit/analysis', search: '' };
  const shared = await import(`../bi_agent/web/static/cockpit/insight-components/shared.js?reg=${Math.random()}`);
  const component = shared.createStageRiskComponent({ name: 'Probe', causesUnderRisks: true });
  assert.ok(component.components && component.components.DeepAnalysisDialog,
    'createStageRiskComponent must register DeepAnalysisDialog');
});

test('the dialog template is valid and teleports to the page body', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  const Vue = await loadVue();
  assert.match(DeepAnalysisDialog.template, /<teleport[^>]+to="body"/);
  assert.doesNotThrow(() => Vue.compile(DeepAnalysisDialog.template));
});

test('opening the dialog shows the chosen cause and prefills an editable prompt', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  const mounted = await mount(DeepAnalysisDialog, { open: true, payload: PAYLOAD, item: CAUSE, root: '' });
  const dialogs = byClass(mounted.tree, 'deep-analysis-dialog');
  assert.equal(dialogs.length, 1);
  assert.match(textOf(dialogs[0]), /深度分析 · 根因/);
  assert.match(textOf(dialogs[0]), /供应链交期延迟/);
  assert.match(textOf(dialogs[0]), /2025-10/);
  const composer = findAll(mounted.tree, node => node.tagName === 'TEXTAREA')[0];
  assert.equal(composer.value, '深度分析「供应链交期延迟」根因');
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(mounted.doc.activeElement, composer, 'the composer takes focus on open');
});

test('sending streams the answer into the dialog and clears the composer afterwards', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  const calls = [];
  const mounted = await mount(DeepAnalysisDialog, { open: true, payload: PAYLOAD, item: CAUSE, root: '' });
  globalThis.window.fetch = async (url, init) => {
    calls.push({ url, body: init && init.body ? JSON.parse(init.body) : null });
    if (String(url).endsWith('/api/analysis360/handoff')) return jsonResponse({ id: 'handoff-1', prompt: 'x' });
    return sseResponse([
      { type: 'text_delta', text: '先在全局本体中定位' },
      { type: 'text_delta', text: '这条根因。' },
      { type: 'done' },
    ]);
  };
  const sendButton = findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__send'))[0];
  trigger(sendButton, 'click');
  await new Promise(resolve => setTimeout(resolve, 30));
  const text = textOf(mounted.tree);
  assert.match(text, /先在全局本体中定位这条根因。/);
  const chat = calls.find(call => String(call.url).endsWith('/api/analysis360/chat'));
  assert.equal(chat.body.analysis360_handoff, 'handoff-1');
  assert.equal(chat.body.session_id, 'session-1');
  const composer = findAll(mounted.tree, node => node.tagName === 'TEXTAREA')[0];
  assert.equal(composer.value, '', 'the composer clears after the first answer');
  const label = textOf(findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__send'))[0]);
  assert.match(label, /发送/);
});

test('a follow-up question reuses the session and never repeats the handoff', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  const calls = [];
  const mounted = await mount(DeepAnalysisDialog, { open: true, payload: PAYLOAD, item: CAUSE, root: '' });
  globalThis.window.fetch = async (url, init) => {
    calls.push({ url, body: init && init.body ? JSON.parse(init.body) : null });
    if (String(url).endsWith('/api/analysis360/handoff')) return jsonResponse({ id: 'handoff-1' });
    if (String(url).endsWith('/api/analysis360/choice')) return sseResponse([{ type: 'text_delta', text: '继续下钻' }, { type: 'done' }]);
    return sseResponse([{ type: 'text_delta', text: '先定位。' }, { type: 'done' }]);
  };
  trigger(findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__send'))[0], 'click');
  await new Promise(resolve => setTimeout(resolve, 25));
  const composer = findAll(mounted.tree, node => node.tagName === 'TEXTAREA')[0];
  composer.listeners['onupdate:modelvalue']('那再查一下订单');
  trigger(findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__send'))[0], 'click');
  await new Promise(resolve => setTimeout(resolve, 25));
  const chats = calls.filter(call => String(call.url).endsWith('/api/analysis360/chat'));
  assert.equal(chats.length, 2);
  assert.equal(chats[0].body.analysis360_handoff, 'handoff-1');
  assert.equal(chats[1].body.analysis360_handoff, undefined);
  assert.equal(chats[1].body.session_id, 'session-1');
});

test('closing before the handoff returns never starts the chat request', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  const calls = [];
  let releaseHandoff;
  const handoffGate = new Promise(resolve => { releaseHandoff = resolve; });
  const mounted = await mount(DeepAnalysisDialog, { open: true, payload: PAYLOAD, item: CAUSE, root: '' });
  globalThis.window.fetch = async url => {
    calls.push(String(url));
    if (String(url).endsWith('/api/analysis360/handoff')) {
      await handoffGate;
      return jsonResponse({ id: 'handoff-1' });
    }
    return sseResponse([{ type: 'done' }]);
  };
  trigger(findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__send'))[0], 'click');
  const close = findAll(mounted.tree, node => String(node.className).includes('deep-analysis-dialog__close'))[0];
  trigger(close, 'click');
  releaseHandoff();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.ok(!calls.some(url => url.endsWith('/api/analysis360/chat')),
    `closing must not start chat after the late handoff (calls: ${calls.join(', ')})`);
});

test('Escape closes the dialog and focus returns to the element that opened it', async () => {
  const { DeepAnalysisDialog } = await loadDialog();
  // A real opener is focused when the dialog mounts, as on a card click.
  const mounted = await mount(DeepAnalysisDialog, { open: true, payload: PAYLOAD, item: CAUSE, root: '' }, { opener: true });
  const opener = mounted.opener;
  const panel = byClass(mounted.tree, 'deep-analysis-dialog')[0];
  assert.equal(panel.listeners.onkeydown === undefined, false, 'the panel owns a keydown handler');
  panel.listeners.onkeydown({
    key: 'Escape', isComposing: false, preventDefault() {}, stopPropagation() {},
  });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(mounted.doc.activeElement, opener, 'focus returns to the card entry');
});

test('SSE frames tolerate CRLF and Chinese split across chunks', async () => {
  const { splitSSEFrames } = await import('../bi_agent/web/static/cockpit/insight-components/deep-analysis/model.js');
  const { events, rest } = splitSSEFrames('data: {"type":"text_delta","text":"根因"}\r\n\r\ndata: {"type":"done"}\r\n\r\n');
  assert.deepEqual(events, [{ type: 'text_delta', text: '根因' }, { type: 'done' }]);
  assert.equal(rest, '');
});

test('Enter sends, Shift+Enter and IME composition do not', async () => {
  const { isSendKey } = await import('../bi_agent/web/static/cockpit/insight-components/deep-analysis/model.js');
  assert.equal(isSendKey({ key: 'Enter', shiftKey: false, isComposing: false }), true);
  assert.equal(isSendKey({ key: 'Enter', shiftKey: true, isComposing: false }), false);
  assert.equal(isSendKey({ key: 'Enter', shiftKey: false, isComposing: true }), false);
  assert.equal(isSendKey({ key: 'Enter', shiftKey: false, keyCode: 229 }), false);
  assert.equal(isSendKey({ key: 'a', shiftKey: false }), false);
});
