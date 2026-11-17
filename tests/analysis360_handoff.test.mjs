import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const read = path => readFile(new URL(path, import.meta.url), 'utf8');
const shared = await read('../bi_agent/web/static/cockpit/insight-components/shared.js');
const index = await read('../bi_agent/web/static/index.html');
const {
  withHandoff, withAnalysis360Routes, analysis360ApiPath, isChatRequest, HANDOFF_FIELD,
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

test('cockpit renders a 深度分析 entry after each root cause only', () => {
  // Both cause layouts (nested under a risk and the flat 原因 section) carry it.
  assert.equal((shared.match(/>深度分析<\/button>/g) || []).length, 2);
  // Risk rows stay plain: the entry is root-cause specific.
  assert.doesNotMatch(shared, /deepAnalysis\('risk'/);
  assert.match(shared, /openCauseDeepAnalysis\(dimension\)/);
  // The entry opens the in-place dialog, not the old workbench tab.
  assert.doesNotMatch(shared, /await openDeepAnalysis\(/);
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
