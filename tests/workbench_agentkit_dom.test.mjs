// Browser-level smoke: the shipped bundle must mount the AgentKit shell.
//
// The route tests prove the server renders the page; this test proves the
// committed IIFE actually boots in a DOM with the shipped template — the
// closest reproducible check to opening the URL in a browser.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
// jsdom is a frontend devDependency; resolve it from the frontend package so
// the test does not require a second node_modules at the repo root.
const frontendRequire = createRequire(resolve(ROOT, 'frontend/package.json'));
const {JSDOM} = frontendRequire('jsdom');
const TEMPLATE = resolve(ROOT, 'bi_agent/web/static/agentkit/index.html');
const BUNDLE = resolve(ROOT, 'bi_agent/web/static/vendor/agentkit/workbench-agentkit.js');

function renderTemplate(template) {
  return template
    .replaceAll('@@APP_ROOT_PATH@@', '')
    .replaceAll('@@AGENTKIT_CSS_VERSION@@', '1')
    .replaceAll('@@AGENTKIT_JS_VERSION@@', '1')
    // The bundle is injected manually so jsdom never tries to load the URL.
    .replace(/<script[^>]*workbench-agentkit\.js[^>]*><\/script>/, '');
}

function sseResponse(window, frames, {delayMs = 0} = {}) {
  const encoder = new window.TextEncoder();
  const stream = new window.ReadableStream({
    async start(controller) {
      for (const frame of frames) {
        if (delayMs) await new Promise((done) => setTimeout(done, delayMs));
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
      }
      controller.close();
    },
  });
  return {ok: true, status: 200, headers: {get: () => null}, body: stream, text: async () => ''};
}

function stubFetch(window, {chatFrames = null, chatDelay = 0, activatePayload = null} = {}) {
  const calls = [];
  window.fetch = async (url, options = {}) => {
    const target = String(url);
    calls.push({url: target, method: options.method || 'GET', body: options.body});
    if (target.includes('api/chat')) {
      if (chatFrames) return sseResponse(window, chatFrames, {delayMs: chatDelay});
      return sseResponse(window, [{type: 'done', turn_id: 't1'}]);
    }
    if (target.includes('/activate')) {
      return {
        ok: true,
        status: 200,
        headers: {get: () => null},
        text: async () => JSON.stringify(activatePayload || {session_id: '', messages: [], agentkit: {}}),
      };
    }
    if (target.includes('api/choice')) {
      return sseResponse(window, [
        {type: 'text_delta', turn_id: 't2', text: '已按选择继续。'},
        {type: 'done', turn_id: 't2'},
      ]);
    }
    const body = target.includes('api/conversations')
      ? {conversations: [{id: 'conv-1', title: 'PACK 未签单商机', updated_at: '2026-11-24T10:00:00'}]}
      : {ok: true};
    return {
      ok: true,
      status: 200,
      headers: {get: () => null},
      text: async () => JSON.stringify(body),
      json: async () => body,
    };
  };
  return calls;
}

async function boot(options = {}) {
  const template = await readFile(TEMPLATE, 'utf8');
  const dom = new JSDOM(renderTemplate(template), {
    url: options.url
      || 'http://localhost/workbench-agentkit?source=v61-cockpit&anchor=PACK_OPP_COVERAGE&period=2026Q3',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const {window} = dom;
  for (const [key, value] of Object.entries(options.sessionStorageSeed || {})) {
    window.sessionStorage.setItem(key, value);
  }
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  // jsdom ships a DOM but not every WHATWG stream/encoding API the runtime uses.
  for (const name of ['TransformStream', 'ReadableStream', 'WritableStream', 'TextDecoder', 'TextEncoder', 'structuredClone']) {
    if (typeof globalThis[name] !== 'undefined' && typeof window[name] === 'undefined') {
      window[name] = globalThis[name];
    }
  }
  // Sigma probes WebGL globals at import time; the smoke test never renders
  // the graph, so the constructors only need to exist.
  window.WebGL2RenderingContext = window.WebGL2RenderingContext || class {};
  window.WebGLRenderingContext = window.WebGLRenderingContext || class {};
  window.matchMedia = window.matchMedia || (() => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  }));
  const calls = stubFetch(window, options);
  window.addEventListener('error', (event) => {
    window.__agentkitErrors = [...(window.__agentkitErrors || []), event.message];
  });
  const bundle = await readFile(BUNDLE, 'utf8');
  window.eval(bundle);
  await new Promise((done) => setTimeout(done, 400));
  return {window, calls};
}

test('the shipped bundle mounts the AgentKit shell with the handoff context', async () => {
  const {window, calls} = await boot();
  const {document} = window;
  const root = document.getElementById('agentkit-root');

  assert.ok(root, 'the template mount point survives');
  assert.equal(root.getAttribute('data-agentkit-runtime'), 'agentkit-runtime:assistant-ui');
  assert.ok(document.querySelector('.ak-shell'), 'AgentKit shell mounted');
  assert.ok(document.querySelector('[data-agentkit-sessions]'), 'session list region');

  // assistant-ui composer input is rendered, not the first-paint skeleton.
  assert.ok(document.querySelector('textarea'), 'composer textarea');
  assert.doesNotMatch(document.body.textContent, /正在加载本体消费展示工作台/);

  // Empty-state copy and the invited question are visible.
  assert.match(document.body.textContent, /从一个经营问题开始/);
  assert.match(document.body.textContent, /PACK 未签单商机/);

  // V6.1 handoff context carried by the URL is shown to the user.
  assert.match(document.body.textContent, /已从来源卡带入分析范围/);
  assert.match(document.body.textContent, /PACK_OPP_COVERAGE/);
  assert.match(document.body.textContent, /2026Q3/);

  // The page loads the conversation list through the shared API contract.
  assert.ok(calls.some((call) => call.url.includes('api/conversations')), 'conversation list requested');
  assert.deepEqual(window.__agentkitErrors || [], []);
});

async function typeAndSend(window, text) {
  const {document} = window;
  const textarea = document.querySelector('textarea');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(textarea, text);
  textarea.dispatchEvent(new window.Event('input', {bubbles: true}));
  await new Promise((done) => setTimeout(done, 80));
  const send = document.querySelector('button.ak-send');
  assert.ok(send, 'send button rendered');
  send.click();
}

test('sending a question streams the answer instead of blanking the page', async () => {
  const {window, calls} = await boot({
    chatFrames: [
      {type: 'text_delta', turn_id: 't1', text: '结论：'},
      {type: 'text_delta', turn_id: 't1', text: 'PACK 未签单涉及 12 家客户。'},
      {type: 'done', turn_id: 't1', stop_reason: 'end'},
    ],
  });
  await typeAndSend(window, 'PACK 未签单商机主要涉及哪些客户？');
  await new Promise((done) => setTimeout(done, 500));

  const {document} = window;
  assert.deepEqual(window.__agentkitErrors || [], [], 'no runtime error after send');
  assert.ok(document.querySelector('.ak-shell'), 'workbench stays mounted after send');
  assert.match(document.body.textContent, /PACK 未签单涉及 12 家客户/, 'streamed answer is visible');
  assert.ok(calls.some((call) => call.url.includes('api/chat')), 'chat request issued');
  // The finished turn is persisted with its structured turns.
  const saveCall = calls.find((call) => call.url.includes('api/conversations/save'));
  assert.ok(saveCall, 'conversation saved after the turn');
  const saved = JSON.parse(saveCall.body);
  assert.equal(saved.agentkit.version, 1);
  assert.equal(saved.agentkit.turns[0].user, 'PACK 未签单商机主要涉及哪些客户？');
  assert.match(saved.session_id, /^agentkit-/);

  // done returns the composer to the send state.
  assert.ok(document.querySelector('button.ak-send'), 'send button restored after done');
  assert.equal(document.querySelector('button.ak-stop'), null, 'stop button removed after done');
});

test('stopping a slow stream keeps the partial answer', async () => {
  const {window} = await boot({
    chatDelay: 120,
    chatFrames: [
      {type: 'text_delta', turn_id: 't1', text: '已取到部分结论'},
      {type: 'text_delta', turn_id: 't1', text: '，仍在补全。'},
      {type: 'done', turn_id: 't1'},
    ],
  });
  await typeAndSend(window, '慢流测试');
  await new Promise((done) => setTimeout(done, 200));
  const stop = window.document.querySelector('button.ak-stop');
  assert.ok(stop, 'stop button appears while streaming');
  stop.click();
  await new Promise((done) => setTimeout(done, 400));

  assert.deepEqual(window.__agentkitErrors || [], []);
  assert.match(window.document.body.textContent, /已取到部分结论/, 'partial answer kept after stop');
  assert.match(window.document.body.textContent, /本轮已停止/, 'interrupt state surfaced');
});

test('the card scope travels with the request and the session survives a refresh', async () => {
  const url = 'http://localhost/workbench-agentkit?source=v61-cockpit'
    + '&anchor=PACK_OPP_COVERAGE&period=2026Q3'
    + '&filters=customer%3D%E5%AE%81%E5%BE%B7%E6%97%B6%E4%BB%A3&evidence=ev-11&handoff=h-7';
  const first = await boot({url, chatFrames: [{type: 'text_delta', turn_id: 't1', text: '按范围分析'},
    {type: 'done', turn_id: 't1'}]});
  await typeAndSend(first.window, 'PACK 未签单商机主要涉及哪些客户？');
  await new Promise((done) => setTimeout(done, 400));

  const firstChat = first.calls.find((call) => call.url.includes('api/chat'));
  assert.ok(firstChat, 'chat request issued');
  const firstBody = JSON.parse(firstChat.body);
  assert.equal(firstBody.message, 'PACK 未签单商机主要涉及哪些客户？');
  assert.equal(firstBody.scope.anchor, 'PACK_OPP_COVERAGE');
  assert.equal(firstBody.scope.period, '2026Q3');
  assert.deepEqual(firstBody.scope.filters, {customer: '宁德时代'});
  assert.deepEqual(firstBody.scope.evidence, ['ev-11']);
  assert.equal(firstBody.scope.handoff_id, 'h-7');

  // Simulate a page refresh: same tab storage, same URL.
  const seed = {};
  for (let index = 0; index < first.window.sessionStorage.length; index += 1) {
    const key = first.window.sessionStorage.key(index);
    seed[key] = first.window.sessionStorage.getItem(key);
  }
  const second = await boot({url, sessionStorageSeed: seed, chatFrames: [{type: 'done', turn_id: 't2'}]});
  await typeAndSend(second.window, '继续追问');
  await new Promise((done) => setTimeout(done, 400));
  const secondBody = JSON.parse(second.calls.find((call) => call.url.includes('api/chat')).body);
  assert.equal(secondBody.session_id, firstBody.session_id,
    'a refresh of the same handoff reuses the established session');
});

test('opening a stored conversation restores the board and keeps the caller session', async () => {
  const activatePayload = {
    session_id: 'agentkit-restore',
    messages: [{role: 'user', content: [{type: 'text', text: 'PACK 缺口'}]}],
    agentkit: {
      version: 1,
      turns: [
        {
          id: 'turn-1',
          user: 'PACK 缺口',
          status: 'done',
          assistant: {
            text: '共 12 家客户。',
            thinking: '',
            tools: [
              {
                id: 'tool-1',
                name: 'TableGenerate',
                status: 'done',
                input: '{"title":"明细"}',
                table: {title: '客户缺口', columns: [{key: 'customer', label: '客户'}], rows: [['宁德时代']]},
                entities: [{code: 'BO_PACK_OPP_002', kind: 'business_object', name: 'PACK 商机'}],
                durationMs: 42,
              },
            ],
          },
        },
      ],
    },
  };
  const {window, calls} = await boot({activatePayload, chatFrames: [{type: 'done', turn_id: 't9'}]});
  const {document} = window;
  const sessionButton = document.querySelector('button.ak-session');
  assert.ok(sessionButton, 'stored conversation listed');
  sessionButton.click();
  await new Promise((done) => setTimeout(done, 400));

  const activateCall = calls.find((call) => call.url.includes('/activate'));
  assert.ok(activateCall, 'activate requested');
  assert.match(activateCall.url, /session_id=agentkit-/, 'restore carries the current session');

  assert.match(document.body.textContent, /共 12 家客户/, 'restored answer text');
  assert.match(document.body.textContent, /宁德时代/, 'restored table row');
  assert.match(document.body.textContent, /TableGenerate/, 'restored tool run');
  assert.match(document.body.textContent, /BO_PACK_OPP_002/, 'restored ontology hit');

  // A follow-up must continue in the restored session.
  await typeAndSend(window, '继续追问');
  await new Promise((done) => setTimeout(done, 400));
  const chat = JSON.parse(calls.find((call) => call.url.includes('api/chat')).body);
  assert.equal(chat.session_id, 'agentkit-restore', 'follow-up reuses the activated session');
});

test('answering a clarification resumes the same turn with the new request id', async () => {
  const {window, calls} = await boot({
    chatFrames: [
      {type: 'text_delta', turn_id: 'request-1', text: '需要确认统计期间。'},
      {
        type: 'user_choice_requested', turn_id: 'request-1', tool_use_id: 'tool-ask',
        question: '统计期间', options: [{id: 'q3', label: '2026Q3'}, {id: 'ytd', label: '本年至今'}],
      },
    ],
  });
  await typeAndSend(window, 'PACK 缺口');
  await new Promise((done) => setTimeout(done, 400));

  const {document} = window;
  assert.match(document.body.textContent, /统计期间/, 'clarification card rendered');
  const checkbox = document.querySelector('.ak-clarify input[type=checkbox]');
  assert.ok(checkbox, 'clarification option rendered');
  checkbox.click();
  await new Promise((done) => setTimeout(done, 80));
  const confirm = document.querySelector('.ak-clarify-actions button');
  confirm.click();
  await new Promise((done) => setTimeout(done, 500));

  const choiceCall = calls.find((call) => call.url.includes('api/choice'));
  assert.ok(choiceCall, 'choice submitted');
  const body = JSON.parse(choiceCall.body);
  assert.deepEqual(body.choice_ids, ['q3']);

  assert.match(document.body.textContent, /已按选择继续/, 'resumed answer visible under the same turn');
  assert.ok(document.querySelector('button.ak-send'), 'composer returns to send state');
  assert.doesNotMatch(document.body.textContent, /正在执行本轮分析/, 'no stuck streaming state');
  assert.deepEqual(window.__agentkitErrors || [], []);
});
