import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = path => readFile(new URL(path, import.meta.url), 'utf8');
const shared = await read('../bi_agent/web/static/cockpit/insight-components/shared.js');
const index = await read('../bi_agent/web/static/index.html');
const {
  withHandoff, withAnalysis360Routes, analysis360ApiPath, isChatRequest, HANDOFF_FIELD,
  withDirect, DIRECT_FIELD, ASSISTANT,
} = await import('../bi_agent/web/static/analysis360-handoff.mjs');

test('the handoff id rides on the first chat request only', async () => {
  const sent = [];
  const fetchImpl = async (url, init) => { sent.push([url, init && init.body]); return {ok: true}; };
  const wrapped = withHandoff(fetchImpl, 'abc123');
  const body = JSON.stringify({message: '深度分析', session_id: 's1'});
  await wrapped('/app/api/meta?session_id=s1');
  await wrapped('/app/api/chat', {method: 'POST', body});
  await wrapped('/app/api/chat', {method: 'POST', body});
  assert.equal(sent[0][1], undefined);
  assert.deepEqual(JSON.parse(sent[1][1]), {message: '深度分析', session_id: 's1', [HANDOFF_FIELD]: 'abc123'});
  assert.deepEqual(JSON.parse(sent[2][1]), {message: '深度分析', session_id: 's1'});
});

test('only POST …/api/chat is a chat request', () => {
  assert.equal(isChatRequest('/root/api/chat', {method: 'POST'}), true);
  assert.equal(isChatRequest('/root/api/chat', {method: 'GET'}), false);
  assert.equal(isChatRequest('/root/api/report/chat', {method: 'POST'}), false);
  assert.equal(isChatRequest('/root/api/choice', {method: 'POST'}), false);
});

test('the analysis window routes chat and choices through 360-only endpoints', async () => {
  assert.equal(analysis360ApiPath('/app/api/chat', 'POST'), '/app/api/analysis360/chat');
  assert.equal(analysis360ApiPath('/app/api/choice?x=1', 'POST'), '/app/api/analysis360/choice?x=1');
  assert.equal(analysis360ApiPath('/app/api/chat', 'GET'), '/app/api/chat');
  const sent = [];
  const fetcher = withAnalysis360Routes(async (url, init) => { sent.push([url, init]); return {ok: true}; });
  await fetcher('/app/api/chat', {method: 'POST', body: '{}'});
  await fetcher('/app/api/choice', {method: 'POST', body: '{}'});
  assert.deepEqual(sent.map(([url]) => url), ['/app/api/analysis360/chat', '/app/api/analysis360/choice']);
});

test('the analysis page loads the handoff module', () => {
  assert.match(index, /static\/analysis360-handoff\.mjs/);
  assert.match(index, /document\.documentElement\.dataset\.analysis360 = '1'/);
  assert.match(index, /html\[data-analysis360="1"\] #antd-sidebar-root/);
  assert.match(index, /html\[data-analysis360="1"\] \.runtime-sidebar-bridge/);
});

test('cockpit rows no longer render 深度分析 buttons', () => {
  assert.doesNotMatch(shared, />深度分析<\/button>/);
  assert.doesNotMatch(shared, /deepAnalysis\('risk'/);
  assert.doesNotMatch(shared, /deepAnalysis\('cause'/);
});

test('the clause is posted to the server and the page opens with only its id', async () => {
  globalThis.window = {Vue: {computed: () => ({}), ref: () => ({}), defineComponent: x => x}};
  globalThis.Vue = globalThis.window.Vue;
  globalThis.document = {querySelector: () => null, head: {appendChild() {}}, createElement: () => ({})};
  globalThis.location = {pathname: '/app/cockpit/analysis', search: ''};
  const module = await import('../bi_agent/web/static/cockpit/insight-components/shared.js');
  assert.equal(module.appRootPath(), '/app');
  const payload = module.deepAnalysisPayload('cause', {
    causeCode: 'RC01', title: '战略客户需求确认未落实', description: '3 条商机', linkedRisks: ['RK02'],
    evidenceIds: ['f1'],
  }, {period: '2025', stage: '商机获取', siblings: [{causeCode: 'RC06', title: '重点跟踪商机承接不足'}],
      facts: [{id: 'f1', label: 'C01', value: 3, unit: '条'}, {id: 'f2', label: '无关', value: 1}]});
  assert.equal(payload.kind, 'cause');
  assert.deepEqual(payload.clause.linkedRisks, ['RK02']);
  assert.deepEqual(payload.facts, [{label: 'C01', value: 3, unit: '条'}]);
  assert.equal(payload.siblings[0].code, 'RC06');
  const calls = [];
  const tab = {location: {replace: url => calls.push(['tab', url])}, close: () => calls.push(['closed'])};
  const opens = [];
  const win = {open: (...args) => { opens.push(args); return tab; }, fetch: async (url, init) => {
    calls.push(['post', url, JSON.parse(init.body).clause.code]);
    return {ok: true, json: async () => ({id: 'h-1'})};
  }};
  const url = await module.openDeepAnalysis(payload, {root: '/app', win});
  assert.equal(url, '/app/workbench?a360=h-1');
  assert.match(opens[0][2], /popup=yes/);
  assert.deepEqual(calls, [['post', '/app/api/analysis360/handoff', 'RC01'], ['tab', '/app/workbench?a360=h-1']]);
  assert.equal(tab.opener, null);
  // A refused handoff closes the blank tab and reports the reason.
  const failing = {open: () => tab, fetch: async () => ({ok: false, status: 400, json: async () => ({detail: '只有风险、问题和根因支持深度分析'})})};
  await assert.rejects(module.openDeepAnalysis(payload, {root: '/app', win: failing}), /只有风险、问题和根因/);
  assert.deepEqual(calls.at(-1), ['closed']);
});

test('the cockpit assistant marks every chat request as a direct 360 question', async () => {
  const sent = [];
  const fetchImpl = async (url, init) => { sent.push([url, init && init.body]); return {ok: true}; };
  const wrapped = withDirect(withAnalysis360Routes(fetchImpl));
  await wrapped('/app/api/chat', {method: 'POST', body: JSON.stringify({message: '本期风险', session_id: 's9'})});
  await wrapped('/app/api/meta?session_id=s9');
  assert.equal(ASSISTANT, 'assistant');
  assert.equal(sent[0][0], '/app/api/analysis360/chat');
  assert.deepEqual(JSON.parse(sent[0][1]), {message: '本期风险', session_id: 's9', [DIRECT_FIELD]: true});
  assert.equal(sent[1][1], undefined);
});

test('the cockpit docks 储小策智能助手 from a bottom-right button', async () => {
  const cockpit = await read('../bi_agent/web/static/cockpit/index.html');
  assert.match(cockpit, /static\/cockpit\/assistant\.js\?v=@@COCKPIT_VERSION@@/);
  const assistant = await import('../bi_agent/web/static/cockpit/assistant.js');
  assert.equal(assistant.ASSISTANT_PATH, '/workbench?a360=assistant');
  assert.equal(assistant.ASSISTANT_NAME, '储小策智能助手');
  assert.equal(assistant.assistantUrl('/bi/'), '/bi/workbench?a360=assistant');
  assert.equal(assistant.assistantUrl(''), '/workbench?a360=assistant');
  // Opening shows the conversation's 看板 (board); 返回主页 keeps only the
  // conversation docked left of the cockpit board (home → workbench chat).
  assert.equal(assistant.workbenchView('board'), 'board');
  assert.equal(assistant.workbenchView('home'), 'chat');
  const panel = await read('../bi_agent/web/static/cockpit/assistant.js');
  assert.match(panel, /const open = \(\) => setView\('board'\)/);
  assert.match(panel, /<span>储小策智能助手<\/span>/);
  assert.doesNotMatch(panel, /requestFullscreen|data-action="full"/);
  const css = await read('../bi_agent/web/static/cockpit/cockpit.css');
  assert.match(css, /\.cockpit-assistant-fab\{position:fixed;right:24px;bottom:24px/);
  assert.match(css, /\.cockpit-assistant\{position:fixed;top:0;bottom:0;left:0;[^}]*width:var\(--cockpit-assistant-w\)/);
  assert.match(css, /\.cockpit-assistant\[data-view="board"\]\{right:0;width:auto/);
  assert.match(css, /html\.cockpit-assistant-docked body\{padding-left:var\(--cockpit-assistant-w\)\}/);
});

test('the cockpit and the workbench agree on the assistant messages', async () => {
  const cockpit = await import('../bi_agent/web/static/cockpit/assistant.js');
  const workbench = await import('../bi_agent/web/static/analysis360-assistant.mjs');
  const origin = 'http://127.0.0.1:8765';
  assert.equal(cockpit.MESSAGE_SOURCE, workbench.MESSAGE_SOURCE);
  // cockpit → workbench: the view
  assert.equal(workbench.readMessage({origin, data: cockpit.viewMessage('board')}, origin, 'view'), 'board');
  assert.equal(workbench.readMessage({origin, data: cockpit.viewMessage('home')}, origin, 'view'), 'chat');
  // workbench → cockpit: 显示对话看板 / 返回主页 / 收起
  for (const request of ['board', 'home', 'close']) {
    assert.equal(cockpit.readRequest({origin, data: workbench.requestMessage(request)}, origin), request);
  }
  // Other origins, other shapes and unknown requests are ignored.
  assert.equal(cockpit.readRequest({origin: 'http://evil.test', data: workbench.requestMessage('board')}, origin), null);
  assert.equal(cockpit.readRequest({origin, data: workbench.requestMessage('delete')}, origin), null);
  assert.equal(cockpit.readRequest({origin, data: 'board'}, origin), null);
  assert.equal(workbench.readMessage({origin, data: {source: 'x', type: 'view', view: 'board'}}, origin, 'view'), null);
});

test('the assistant workbench: no sidebar, 显示对话看板 / 返回主页, 历史对话 by the model chip, new welcome', async () => {
  // a360=assistant does not switch the page into the focused 360 layout; it is
  // marked as the docked assistant before the first paint instead.
  assert.match(index, /a360 !== null && a360 !== 'assistant'/);
  assert.match(index, /document\.documentElement\.dataset\.analysis360Assistant = '1'/);
  assert.match(index, /static\/analysis360-assistant\.css\?v=1/);
  assert.match(index, /analysis360-handoff\.mjs\?v=5/);
  const handoff = await read('../bi_agent/web/static/analysis360-handoff.mjs');
  const assistantBranch = handoff.slice(handoff.indexOf('if (handoffId === ASSISTANT)'), handoff.indexOf('return false;', handoff.indexOf('if (handoffId === ASSISTANT)')));
  assert.doesNotMatch(assistantBranch, /markMode/);
  assert.match(assistantBranch, /mountAssistantMode\(window, document\)/);
  assert.match(assistantBranch, /document\.title = "储小策智能助手"/);
  const module = await read('../bi_agent/web/static/analysis360-assistant.mjs');
  assert.match(module, /"显示对话看板"/);
  assert.match(module, /"返回主页"/);
  assert.match(module, /home\.addEventListener\("click", \(\) => send\("home"\)\)/);
  assert.match(module, /showBoard\.addEventListener\("click", \(\) => send\("board"\)\)/);
  assert.match(module, /"储小策，"/);
  assert.match(module, /"我帮你"/);
  assert.match(module, /"看目标 · 看差距 · 看趋势"/);
  assert.match(module, /chip\.after\(button\)/);
  assert.match(module, /<span>历史对话<\/span>/);
  assert.match(module, /getElementById\("recent-list"\)/);
  const css = await read('../bi_agent/web/static/analysis360-assistant.css');
  assert.match(css, /html\[data-analysis360-assistant\] #antd-sidebar-root/);
  assert.match(css, /html\[data-analysis360-assistant\] #pro-ui-welcome-root,\r?\nhtml\[data-analysis360-assistant\] #chat-empty \{ display: none !important; \}/);
  assert.match(css, /html\[data-analysis360-assistant\]\[data-a360-view="board"\] body \.split > \.dashboard-pane \{\r?\n  display: flex !important;/);
  assert.match(css, /html\[data-analysis360-assistant\] body \.split > \.dashboard-pane \{ display: none !important; \}/);
  // The composer chip still cannot cover the input row.
  const built = await read('../bi_agent/web/static/vendor/antd/eimosp-ontology-agentic-analytics-workbench.css');
  assert.match(built, /\.pro-ui-model-chip\.ant-btn\{max-width:min\(220px,100%\);min-width:0/);
  assert.match(index, /workbench\.css\?v=137/);
});
