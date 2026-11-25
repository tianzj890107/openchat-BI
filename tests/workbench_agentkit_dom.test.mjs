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
const BUNDLE = process.env.AGENTKIT_TEST_BUNDLE || resolve(ROOT, 'bi_agent/web/static/vendor/agentkit/workbench-agentkit.js');

function renderTemplate(template) {
  return template
    .replaceAll('@@APP_ROOT_PATH@@', '')
    .replaceAll('@@APP_VERSION@@', 'ontology-v0.0.0')
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

function stubFetch(window, {chatFrames = null, chatDelay = 0, activatePayload = null, endpoints = {}} = {}) {
  const calls = [];
  window.fetch = async (url, options = {}) => {
    const target = String(url);
    calls.push({url: target, method: options.method || 'GET', body: options.body});
    const handler = endpoints[target.split('?')[0]];
    if (handler) {
      const {body, status = 200} = handler(options);
      return {ok: status < 400, status, text: async () => JSON.stringify(body)};
    }
    if (target.includes('api/chat') || target.includes('api/report/chat')) {
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
    if (target.includes('api/choice') || target.includes('api/report/choice')) {
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
  const search = document.querySelector('input[aria-label="搜索会话"]');
  assert.equal(search.previousElementSibling?.textContent, '新建会话');
  assert.equal(Boolean(document.querySelector('button[aria-label="刷新会话"]')), false);
  assert.equal(Array.from(document.querySelectorAll('button')).some((button) => button.textContent === '回收站'), false);

  // assistant-ui composer input is rendered, not the first-paint skeleton.
  assert.ok(document.querySelector('textarea'), 'composer textarea');
  const attachment = document.querySelector('button[aria-label="添加附件"]');
  assert.equal(attachment?.closest('.ak-composer-entry')?.querySelector('textarea'), document.querySelector('textarea'));
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
  const first = await boot({url, chatFrames: [
    {type: 'scope_accepted', turn_id: 't1', scope: {anchor: 'PACK_OPP_COVERAGE', period: '2026Q3'}},
    {type: 'text_delta', turn_id: 't1', text: '按范围分析'},
    {type: 'done', turn_id: 't1'},
  ]});
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
  assert.match(first.window.document.body.textContent, /分析服务已核对范围/, 'accepted scope is confirmed in the page');

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
  document.querySelector('[data-slot="tool-group-trigger"]').click();
  await waitFor(() => document.querySelector('[data-slot="tool-group-item"]'));
  const tool = document.querySelector('[data-slot="tool-group-item"]');
  assert.match(tool.textContent, /TableGenerate/, 'restored tool run');
  tool.querySelector('summary')?.click();
  assert.match(tool.textContent, /BO_PACK_OPP_002/, 'restored ontology hit');
  assert.equal(
    calls.filter((call) => call.url.includes('api/conversations/save')).length,
    0,
    'opening a stored conversation must not write to it',
  );

  // A follow-up must continue in the restored session.
  await typeAndSend(window, '继续追问');
  await new Promise((done) => setTimeout(done, 400));
  const chat = JSON.parse(calls.find((call) => call.url.includes('api/chat')).body);
  assert.equal(chat.session_id, 'agentkit-restore', 'follow-up reuses the activated session');

  const saves = calls.filter((call) => call.url.includes('api/conversations/save'));
  assert.equal(saves.length, 1, 'only the produced turn is saved');
  const savedTurns = JSON.parse(saves[0].body).agentkit.turns;
  assert.equal(savedTurns.length, 2, 'history and the new turn are saved together');
  assert.notEqual(savedTurns[0].id, savedTurns[1].id, 'turn ids stay unique after restore');
  assert.ok(
    calls.filter((call) => call.url.includes('api/conversations') && !call.url.includes('save')).length >= 2,
    'conversation list refreshes after saving',
  );
});

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 50; attempt++) {
    const result = predicate();
    if (result) return result;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  return null;
}

function findButton(document, label) {
  return [...document.querySelectorAll('button')].find((button) => button.textContent.trim() === label);
}

test('tool details own their evidence and single-anchor subgraph actions', async () => {
  const {window, calls} = await boot({
    chatFrames: [
      {type: 'tool_start', id: 'lookup', name: 'Ontology-SemanticQuery'},
      {type: 'tool_result', id: 'lookup', name: 'Ontology-SemanticQuery',
        input: {query: '客户覆盖'}, output: '命中客户覆盖指标', duration_ms: 42,
        ontology_entities: [{code: 'M_COVERAGE', kind: 'indicator', name: '覆盖率', repository_id: 'repo-a'}]},
      {type: 'tool_result', id: 'fallback', name: 'Ontology-RelationQuery', output: '关系检索失败',
        execution_status: 'FAILED', error_code: 'UPSTREAM_TIMEOUT',
        ontology_entities: [{code: 'BO_CUSTOMER', kind: 'business_object', name: '客户', repository_id: 'repo-a'}]},
      {type: 'tool_result', id: 'chart', name: 'TableGenerate',
        table: {title: '客户结果表', columns: [{key: 'customer'}], rows: [['样例客户']]}},
      {type: 'done'},
    ],
    endpoints: {'/api/ontology/subgraph': () => ({body: {nodes: [], links: []}})},
  });
  const {document} = window;
  await typeAndSend(window, '跟踪证据');
  await waitFor(() => document.querySelector('.ak-board').textContent.includes('客户结果表'));
  assert.match(document.querySelector('.ak-board').textContent, /客户结果表/);
  assert.doesNotMatch(document.querySelector('.ak-board').textContent, /证据 · 工具过程|本体命中|M_COVERAGE/);
  const trigger = document.querySelector('[data-slot="tool-group-trigger"]');
  if (trigger.getAttribute('aria-expanded') === 'false') trigger.click();
  await waitFor(() => document.querySelectorAll('[data-slot="tool-group-item"]').length === 3);
  const lookup = [...document.querySelectorAll('[data-slot="tool-group-item"]')].find((item) => item.textContent.includes('Ontology-SemanticQuery'));
  const fallback = [...document.querySelectorAll('[data-slot="tool-group-item"]')].find((item) => item.textContent.includes('Ontology-RelationQuery'));
  lookup.querySelector('summary').click();
  fallback.querySelector('summary').click();
  assert.match(lookup.textContent, /客户覆盖.*命中客户覆盖指标/s);
  assert.match(lookup.textContent, /42 ms/);
  assert.match(fallback.textContent, /UPSTREAM_TIMEOUT/);
  assert.doesNotMatch(lookup.textContent, /BO_CUSTOMER/);
  lookup.querySelector('[data-ontology-code="M_COVERAGE"]').click();
  await waitFor(() => document.querySelector('[role="dialog"]')?.textContent.includes('没有可展示'));
  findButton(document, '关系扩散').click();
  await waitFor(() => calls.filter((call) => call.url.includes('/api/ontology/subgraph')).length === 2);
  const graphCalls = calls.filter((call) => call.url.includes('/api/ontology/subgraph'))
    .map((call) => JSON.parse(call.body));
  const session = JSON.parse(calls.find((call) => call.url.includes('/api/chat')).body).session_id;
  assert.deepEqual(graphCalls, ['context', 'expand'].map((strategy) => ({
    code: 'M_COVERAGE', type: 'indicator', repository_id: 'repo-a', session_id: session, strategy,
  })));
});

test('workbench settings save paired sources and models and keep history on its own source', async () => {
  const pairs = [
    {name: '样例库 A', value: 'repo:a', databaseValue: 'db:a', dorisDatabase: 'schema_a'},
    {name: '样例库 B', value: 'repo:b', databaseValue: 'db:b', dorisDatabase: 'schema_b'},
  ];
  const config = {
    models: [{model_key: 'test-model', label: '样例模型', max_output_tokens: 20000, supports_thinking: true}],
    current: {model_key: 'test-model', max_tokens: 8000, temperature: 0.5, thinking: false},
  };
  let rejectSource = true;
  const {window, calls} = await boot({
    activatePayload: {session_id: 'agentkit-history', messages: [{role: 'user', content: '旧会话问题'}]},
    endpoints: {
      '/api/sources': (options) => options.method === 'PUT'
        ? rejectSource
          ? (rejectSource = false, {status: 400, body: {detail: '源暂不可用'}})
          : {body: {...JSON.parse(options.body), changed: ['ontology', 'database']}}
        : {body: {
          ontology: {active: 'repo:a', options: pairs.map((pair) => pair.value), remote_repositories: pairs},
          database: {active: 'db:a', options: pairs.map((pair) => pair.databaseValue), remote_databases: pairs},
          retrieval: {mode: 'semantic', graph: {options: []}},
        }},
      '/api/config': (options) => ({body: options.method === 'PUT'
        ? {...config, current: JSON.parse(options.body)} : config}),
    },
  });
  const {document} = window;
  document.querySelector('button.ak-session').click();
  await waitFor(() => document.querySelector('.ak-turn')?.textContent.includes('旧会话问题'));
  assert.ok(!document.querySelector('.ak-topbar'), 'the page has no shared top bar');
  assert.match(document.querySelector('.ak-sessions').textContent, /智能分析.*ontology-v0\.0\.0/);
  const settings = findButton(document, '切换本体库/数据源');
  assert.ok(settings?.closest('.ak-nav-footer'), 'source settings are in the navigation footer');
  settings.click();
  const ontology = await waitFor(() => document.querySelector('select[name="ontology"]'));
  assert.ok(ontology);
  ontology.value = 'repo:b';
  ontology.dispatchEvent(new window.Event('change', {bubbles: true}));
  const database = document.querySelector('select[name="database"]');
  await waitFor(() => database.value === 'db:b');
  assert.equal(database.value, 'db:b');
  findButton(document, '保存本体库与数据源').click();
  assert.ok(await waitFor(() => document.querySelector('[role="alert"]')?.textContent.includes('源暂不可用')));
  assert.match(document.querySelector('.ak-turn').textContent, /旧会话问题/);
  findButton(document, '保存本体库与数据源').click();
  assert.ok(await waitFor(() => [...document.querySelectorAll('[role="status"]')].some((item) => item.textContent.includes('数据源已保存'))));
  assert.equal(document.querySelector('.ak-turn'), null, 'save opens a new conversation');

  assert.equal(document.querySelector('input[name="thinking"]'), null);
  document.querySelector('button.ak-close[aria-label="关闭切换本体库/数据源"]').click();
  const modelButton = await waitFor(() => findButton(document, '样例模型'));
  assert.ok(modelButton?.closest('.ak-composer'), 'the current model is displayed inside the composer');
  assert.ok(document.querySelector('.ak-send')?.closest('.ak-composer'));
  modelButton.click();
  const thinking = await waitFor(() => document.querySelector('input[name="thinking"]'));
  assert.ok(thinking, 'model settings open from the composer button');
  thinking.click();
  findButton(document, '保存模型').click();
  assert.ok(await waitFor(() => [...document.querySelectorAll('[role="status"]')].some((item) => item.textContent.includes('模型已保存'))));
  const modelPut = calls.find((call) => call.url === '/api/config' && call.method === 'PUT');
  assert.deepEqual(JSON.parse(modelPut.body), {...config.current, thinking: true});

  document.querySelector('button.ak-close[aria-label="关闭模型"]').click();
  await typeAndSend(window, '用新配置分析');
  await waitFor(() => calls.some((call) => call.url === '/api/chat'));
  const sourcePuts = calls.filter((call) => call.url === '/api/sources' && call.method === 'PUT');
  const saved = JSON.parse(sourcePuts.at(-1).body);
  assert.equal(saved.ontology, 'repo:b');
  assert.equal(saved.database, 'db:b');
  const chat = calls.find((call) => call.url === '/api/chat');
  assert.equal(JSON.parse(chat.body).session_id, saved.session_id);
  assert.notEqual(saved.session_id, 'agentkit-history');

  document.querySelector('button.ak-new').click();
  await typeAndSend(window, '新会话沿用默认源');
  await waitFor(() => calls.filter((call) => call.url === '/api/chat').length === 2);
  const nextSource = calls.filter((call) => call.url === '/api/sources' && call.method === 'PUT').at(-1);
  const nextChat = calls.filter((call) => call.url === '/api/chat').at(-1);
  assert.equal(JSON.parse(nextSource.body).ontology, 'repo:b');
  assert.equal(JSON.parse(nextChat.body).session_id, JSON.parse(nextSource.body).session_id);
  assert.notEqual(JSON.parse(nextChat.body).session_id, saved.session_id);
  assert.ok(calls.indexOf(nextSource) < calls.indexOf(nextChat), 'bind the source before sending the question');
});

test('the pinned collapsible SOP shows real progress and finished tools can be reopened', async () => {
  const {window} = await boot({
    chatDelay: 140,
    chatFrames: [
      {type: 'sop_progress', step: 1, detail: '识别经营问题'},
      {type: 'tool_start', id: 't', name: 'Ontology-SemanticQuery'},
      {type: 'sop_progress', step: 3, detail: '规划校验'},
      {type: 'tool_result', id: 't', name: 'Ontology-SemanticQuery', output: '已有证据'},
      {type: 'text_delta', text: '已完成检查'},
      {type: 'done'},
    ],
  });
  const {document} = window;
  const sop = document.querySelector('[data-agentkit-sop]');
  assert.ok(sop?.closest('.ak-thread'));
  assert.equal(sop.closest('.ak-transcript'), null, 'SOP stays above the scrollable transcript');
  await typeAndSend(window, '验证 SOP 和工具');
  const trigger = await waitFor(() => document.querySelector('[data-slot="tool-group-trigger"]'));
  assert.ok(trigger);
  if (trigger.getAttribute('aria-expanded') !== 'true') trigger.click();
  assert.equal(await waitFor(() => trigger.getAttribute('aria-expanded') === 'true'), true);
  assert.equal(document.querySelector('.ak-answer--muted'), null);
  assert.ok(await waitFor(() => document.querySelector('.ak-send')));
  const finished = document.querySelector('[data-slot="tool-group-trigger"]');
  assert.equal(finished.getAttribute('aria-expanded'), 'false');
  finished.click();
  assert.ok(await waitFor(() => document.querySelector('[data-slot="tool-group-item"]')));
  assert.match(sop.textContent, /2\/2/);
  sop.querySelector('summary').click();
  assert.match(sop.textContent, /本轮无需执行.*本体模型匹配/s);
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

test('a restored conversation keeps each turn board separate and never invents zeros', async () => {
  const activatePayload = {
    session_id: 'agentkit-restore-2',
    messages: [],
    agentkit: {
      version: 1,
      turns: [
        {
          id: 'turn-1', user: '第一轮：客户明细', status: 'done',
          assistant: {text: '第一轮结论', tools: [{
            id: 'tool-1', name: 'TableGenerate', status: 'done', input: '{}',
            table: {title: '第一轮明细', columns: [{key: 'customer', label: '客户'}], rows: [['宁德时代']]},
          }]},
        },
        {
          id: 'turn-2', user: '第二轮：缺口图', status: 'done',
          sop: {step: 3, visited: [3], todos: [{content: '数据获取和可视化', status: 'completed'}]},
          assistant: {text: '第二轮结论', tools: [{
            id: 'tool-2', name: 'ChartGenerate', status: 'done', input: '{}',
            chart: {
              title: '第二轮缺口图', chart_type: 'bar',
              option: {xAxis: {data: ['宁德时代', '比亚迪']}, series: [{name: '缺口', data: [3, null]}]},
            },
          }]},
        },
      ],
    },
  };
  const {window} = await boot({activatePayload});
  window.document.querySelector('button.ak-session').click();
  await new Promise((done) => setTimeout(done, 400));

  const groups = [...window.document.querySelectorAll('details.ak-turn-results')];
  const sopBars = window.document.querySelectorAll('[data-agentkit-sop]');
  assert.equal(sopBars.length, 1, 'restoring a conversation replaces the empty SOP');
  assert.match(sopBars[0].querySelector('summary').textContent, /1\/1/);
  assert.equal(groups.length, 2, 'one board group per turn');
  assert.match(groups[0].textContent, /第一轮明细/);
  assert.doesNotMatch(groups[0].textContent, /第二轮缺口图/);
  assert.match(groups[1].textContent, /第二轮缺口图/);
  assert.match(groups[1].textContent, /—/, 'missing chart value renders as a dash');
  assert.doesNotMatch(groups[1].textContent, /缺口\s*0/, 'missing value is never rendered as zero');
});

test('refreshing a V6.1 card reopens the conversation it already produced', async () => {
  const url = 'http://localhost/workbench-agentkit?source=v61-cockpit'
    + '&anchor=PACK_OPP_COVERAGE&period=2026Q3&handoff=h-7';
  const activatePayload = {
    session_id: 'agentkit-h-7-abc',
    messages: [],
    agentkit: {version: 1, turns: [{
      id: 'turn-1', user: 'PACK 未签单商机', status: 'done',
      assistant: {text: '已恢复到该卡的会话', tools: []},
    }]},
  };
  const {window, calls} = await boot({
    url,
    activatePayload,
    sessionStorageSeed: {
      'agentkit.handoff-session.h-7': 'agentkit-h-7-abc',
      'agentkit.handoff-conversation.h-7': 'conv-7',
    },
    chatFrames: [{type: 'done', turn_id: 't9'}],
  });
  await new Promise((done) => setTimeout(done, 500));

  const activateCall = calls.find((call) => call.url.includes('/activate'));
  assert.ok(activateCall, 'the card conversation is reopened on load');
  assert.match(activateCall.url, /conversations\/conv-7\/activate\?unified=true&session_id=agentkit-h-7-abc/);
  assert.match(window.document.body.textContent, /已恢复到该卡的会话/);
  assert.doesNotMatch(window.document.body.textContent, /从一个经营问题开始/, 'no empty state');
  assert.equal(
    calls.filter((call) => call.url.includes('api/conversations/save')).length,
    0,
    'reopening the card conversation writes nothing',
  );
});

test('default entry submits an incoming question once in the unified workspace', async () => {
  const {window, calls} = await boot({url: 'http://localhost/workbench?prompt=%E8%BF%9B%E5%85%A5%E9%97%AE%E9%A2%98'});
  try {
    assert.equal(calls.filter(({url}) => url === '/api/chat').length, 1);
    assert.equal(new window.URL(window.location.href).searchParams.has('prompt'), false);
    assert.equal(Boolean(window.document.querySelector('[aria-label="分析模式"]')), false);
    assert.ok(window.document.querySelector('.ak-composer [aria-label="添加附件"]'));
    assert.ok(calls.some(({url}) => url === '/api/conversations'));
  } finally {
    window.close();
  }
});

test('legacy assets appear in the new history, and a board question locates the original turn', async () => {
  const {window, calls} = await boot({
    activatePayload: {session_id: 'legacy-target', mode: 'data', messages: [], agentkit: {}},
    endpoints: {
      '/api/conversations/conv-1/assets': () => ({body: {
        chat_html: '<div class="msg-user" data-turn="3"><p class="msg-body">旧问题</p></div>' +
          '<div class="msg-assistant"><div class="msg-body">旧结论<script>throw 1</script></div></div>',
        dashboard_html: '<div class="dash-card dash-table" data-turn="3"><span class="dash-title">旧明细</span>' +
          '<table><thead><tr><th>地区</th></tr></thead><tbody><tr><td>华东</td></tr></tbody></table></div>',
        sop_steps: [{content: '核对数据口径', status: 'completed'}],
      }}),
      '/api/report/compose': () => ({body: {title: '结构化管报', summary: '执行摘要', sections: [{heading: '第一章', blocks: [0]}]}}),
    },
  });
  try {
    const {document} = window;
    document.querySelector('.ak-session').click();
    await new Promise((done) => setTimeout(done, 120));
    assert.match(document.querySelector('.ak-assistant').textContent, /旧结论/);
    assert.doesNotMatch(document.querySelector('.ak-assistant').textContent, /throw 1/);
    assert.match(document.querySelector('.ak-board table').textContent, /华东/);
    document.querySelector('.ak-turn-question').click();
    await new Promise((done) => setTimeout(done, 100));
    assert.equal(document.activeElement.textContent, '旧问题');
    assert.equal(document.querySelector('[aria-label="问题定位"] button').textContent, '1. 旧问题');
    const word = [...document.querySelectorAll('.ak-delivery button')].find((button) => button.textContent === '导出 Word');
    word.click();
    await new Promise((done) => setTimeout(done, 100));
    const compose = calls.find(({url}) => url === '/api/report/compose');
    assert.equal(JSON.parse(compose.body).blocks[0].kind, 'table');
    assert.match(document.querySelector('.ak-delivery').textContent, /下载 Word/);
    assert.equal(calls.filter(({url}) => url === '/api/conversations/save').length, 0);
  } finally { window.close(); }
});

test('upload adds context to the current conversation and removal resumes ordinary questions', async () => {
  const {window, calls} = await boot({
    url: 'http://localhost/workbench',
    endpoints: {
      '/api/conversations/save': () => ({body: {id: 'saved-1'}}),
      '/api/report/upload': () => ({body: {id: 'pdf-1', filename: '经营简报.pdf'}}),
      '/api/report/attachments': ({body}) => {
        const {report_ids} = JSON.parse(body);
        return {body: {active_reports: report_ids.map((id) => ({id, filename: '经营简报.pdf'})),
          has_session: report_ids.length > 0, with_db: true}};
      },
    },
  });
  try {
    const {document} = window;
    await typeAndSend(window, '先看经营数据');
    await waitFor(() => calls.some(({url}) => url === '/api/conversations/save'));
    document.querySelector('.ak-composer [aria-label="添加附件"]').click();
    await waitFor(() => [...document.querySelectorAll('button')].some((node) => node.textContent === '上传文件'));
    [...document.querySelectorAll('button')].find((node) => node.textContent === '上传文件').click();
    const input = document.querySelector('.ak-composer input[type=file]');
    Object.defineProperty(input, 'files', {value: [new window.File(['fixture'], '经营简报.pdf', {type: 'application/pdf'})]});
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
    await waitFor(() => document.querySelector('[aria-label="移除经营简报.pdf"]'));
    assert.equal(document.querySelector('textarea').value, '请分析上传的附件。');
    assert.equal(calls.filter(({url}) => url === '/api/report/chat').length, 0);
    const attach = JSON.parse(calls.find(({url}) => url === '/api/report/attachments').body);
    assert.deepEqual(attach.report_ids, ['pdf-1']);
    assert.equal(attach.from_mode, 'data');
    assert.equal(attach.session_id, JSON.parse(calls.find(({url}) => url === '/api/chat').body).session_id);
    await typeAndSend(window, '核对报表金额');
    await waitFor(() => calls.some(({url}) => url === '/api/report/chat'));
    assert.equal(JSON.parse(calls.find(({url}) => url === '/api/report/chat').body).session_id, attach.session_id);
    await waitFor(() => calls.some(({url, body}) => url === '/api/conversations/save' &&
      JSON.parse(body).agentkit.turns.some(({user}) => user === '核对报表金额')));
    const savedReport = calls.filter(({url, body}) => url === '/api/conversations/save' && JSON.parse(body).runtime_mode === 'report').at(-1);
    assert.equal(JSON.parse(savedReport.body).cid, 'saved-1');
    assert.equal(JSON.parse(savedReport.body).mode, 'data');
    assert.deepEqual(JSON.parse(savedReport.body).agentkit.turns.at(-1).attachments, ['经营简报.pdf']);
    document.querySelector('[aria-label="移除经营简报.pdf"]').click();
    await waitFor(() => !document.querySelector('[aria-label="移除经营简报.pdf"]'));
    await typeAndSend(window, '继续看经营数据');
    await waitFor(() => calls.filter(({url}) => url === '/api/chat').length === 2);
    await waitFor(() => document.querySelector('.ak-transcript')?.textContent.includes('继续看经营数据'));
    assert.deepEqual(window.__agentkitErrors || [], []);
    assert.match(document.querySelector('.ak-transcript').textContent, /先看经营数据.*经营简报.pdf.*核对报表金额.*继续看经营数据/s);
    const separator = document.querySelector('.ak-divider--thread');
    separator.dispatchEvent(new window.KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
    await waitFor(() => separator.getAttribute('aria-valuenow') === '44');
    assert.equal(window.localStorage.getItem('agentkit.layout.threadPercent'), '44');
  } finally { window.close(); }
});

test('standard report wizard is available in the attachment menu and uses the current conversation', async () => {
  const {window, calls} = await boot({url: 'http://localhost/workbench?mode=report'});
  try {
    const {document} = window;
    const button = (label) => [...document.querySelectorAll('button')].find((node) => node.textContent === label);
    document.querySelector('[aria-label="添加附件"]').click();
    await waitFor(() => button('标准报表生成'));
    button('标准报表生成').click();
    await waitFor(() => button('确认生成'));
    button('确认生成').click();
    await waitFor(() => button('确认 · 开启报表生成'));
    button('确认 · 开启报表生成').click();
    await waitFor(() => calls.some(({url}) => url === '/api/report/chat'));
    const generator = calls.find(({url}) => url.startsWith('/api/report/generate?'));
    const question = JSON.parse(calls.find(({url}) => url === '/api/report/chat').body);
    assert.equal(new window.URL(generator.url, window.location.href).searchParams.get('session_id'), question.session_id);
    assert.match(question.message, /标准报表生成任务.*报表期间.*模板.*配图/s);
    assert.equal(question.visible_user_text, '生成标准报表');
  } finally { window.close(); }
});

test('reopened report history shares the session list and keeps attachments and the draft on upload failure', async () => {
  const {window, calls} = await boot({
    url: 'http://localhost/workbench',
    activatePayload: {
      session_id: 'restored-report', mode: 'report', runtime_mode: 'report',
      report_context: {active_reports: [{id: 'old', filename: '既有报表.pdf'}], has_session: true, with_db: false},
      messages: [{role: 'user', content: '上次报表问题'}],
    },
    endpoints: {
      '/api/report/upload': () => ({status: 400, body: {detail: '文档无法解析'}}),
    },
  });
  try {
    const {document} = window;
    document.querySelector('.ak-session').click();
    assert.ok(await waitFor(() => document.querySelector('[aria-label="移除既有报表.pdf"]')));
    assert.ok(document.querySelector('.ak-transcript').textContent.includes('上次报表问题'));
    const textarea = document.querySelector('textarea');
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, '保留这条草稿');
    textarea.dispatchEvent(new window.Event('input', {bubbles: true}));
    const input = document.querySelector('.ak-composer input[type=file]');
    Object.defineProperty(input, 'files', {value: [new window.File(['fixture'], '坏文件.pdf')]});
    input.dispatchEvent(new window.Event('change', {bubbles: true}));
    assert.ok(await waitFor(() => document.querySelector('.ak-attachment-notice')?.textContent.includes('坏文件.pdf · 文档无法解析')));
    assert.equal(textarea.value, '保留这条草稿');
    assert.ok(document.querySelector('[aria-label="移除既有报表.pdf"]'));
    assert.ok(!calls.some(({url}) => url === '/api/report/attachments' || url === '/api/conversations/save'));
    await typeAndSend(window, '继续问原报表');
    assert.ok(await waitFor(() => calls.some(({url}) => url === '/api/report/chat')));
    assert.equal(JSON.parse(calls.find(({url}) => url === '/api/report/chat').body).session_id, 'restored-report');
  } finally { window.close(); }
});
