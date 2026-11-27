import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';

const require = createRequire(new URL('../frontend/', import.meta.url));
const {JSDOM} = require('jsdom');
const bundle = await readFile(new URL('../bi_agent/web/static/vendor/agentkit/workbench-agentkit.js', import.meta.url), 'utf8');

function sseResponse(frames) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader() {
        return {
          async read() {
            if (index >= frames.length) return {done: true, value: undefined};
            return {done: false, value: encoder.encode(`data: ${JSON.stringify(frames[index++])}\n\n`)};
          },
        };
      },
    },
    text: async () => '',
    json: async () => ({}),
  };
}

function jsonResponse(body) {
  return {ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body)};
}

async function waitFor(predicate, timeout = 4000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const value = predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('timeout waiting for DOM');
}

async function boot({view = 'board'} = {}) {
  const dom = new JSDOM('<!doctype html><html><body><div id="agentkit-root" data-app-version="ontology-v0.1.16"></div></body></html>', {
    url: `https://cockpit.example/app/workbench?a360=assistant&view=${view}`,
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const {window} = dom;
  for (const key of ['TransformStream', 'ReadableStream', 'TextEncoder', 'TextDecoder', 'MessageChannel', 'MessagePort', 'Response', 'Request', 'Headers']) {
    if (globalThis[key] && !window[key]) window[key] = globalThis[key];
  }
  window.ResizeObserver ||= class { observe() {} unobserve() {} disconnect() {} };
  window.WebGL2RenderingContext ||= class WebGL2RenderingContext {};
  window.WebGLRenderingContext ||= class WebGLRenderingContext {};
  window.HTMLCanvasElement.prototype.getContext ||= () => null;
  window.matchMedia ||= () => ({matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}});
  window.scrollTo ||= () => {};
  window.APP_ROOT_PATH = '/app';
  const calls = [];
  window.fetch = async (url, init = {}) => {
    const target = String(url);
    calls.push({url: target, method: String(init.method || 'GET').toUpperCase(), body: init.body});
    if (target.endsWith('/api/meta')) {
      return jsonResponse({agent: {model: '团队模型 · 深度分析'}});
    }
    if (target.endsWith('/api/analysis360/history')) {
      return jsonResponse({conversations: []});
    }
    if (target.includes('/api/analysis360/chat')) {
      return sseResponse([{type: 'text_delta', text: '先看商机覆盖。'}, {type: 'done'}]);
    }
    if (target.includes('/api/analysis360/history/')) {
      return jsonResponse({id: 'x', title: 'x', turns: []});
    }
    return jsonResponse({});
  };
  window.eval(bundle);
  const root = window.document.getElementById('agentkit-root');
  await waitFor(() => root.querySelector('.ak-brand'));
  return {dom, window, root, calls};
}

test('the assistant opens the complete AgentKit workbench, not a reduced embed', async () => {
  const {root} = await boot();
  assert.equal(root.querySelector('.ak-brand-name')?.textContent, '储小策智能助手');
  assert.ok(root.querySelector('.ak-sessions'), 'session sidebar is mounted');
  assert.ok(root.querySelector('.ak-session-pane'), 'shared SessionList container is mounted');
  assert.ok(root.querySelector('.ak-nav-footer'), 'bottom navigation is mounted');
  assert.ok(root.querySelector('[data-agentkit-thread]'), 'conversation column is mounted');
  assert.ok(root.querySelector('[data-agentkit-board]'), 'board column is mounted');
  assert.ok(root.querySelector('.ak-composer-input'), 'sticky composer is mounted');
  assert.equal(root.querySelectorAll('.ak-divider').length, 2, 'both shared dividers are mounted');
  assert.equal(root.querySelector('.ak-shell').dataset.akView, 'board');
  assert.match(root.textContent, /返回主页/);
  assert.match(root.textContent, /收起/);
  assert.match(root.textContent, /本体库\/数据源（只读）/);
});

test('questions go to the 360 endpoints and never touch generic configuration APIs', async () => {
  const {root, calls, window} = await boot();
  [...root.querySelectorAll('.ak-suggestions button')][0].click();
  const send = await waitFor(() => root.querySelector('.ak-send'));
  send.click();
  await waitFor(() => calls.some((call) => call.url.includes('/api/analysis360/chat')));
  const chat = calls.find((call) => call.url.includes('/api/analysis360/chat'));
  const body = JSON.parse(chat.body);
  assert.equal(body.analysis360_direct, true);
  assert.ok(chat.url.endsWith('/app/api/analysis360/chat'));
  for (const forbidden of ['/api/config', '/api/sources', '/api/conversations', '/api/report', '/api/roles']) {
    assert.equal(calls.some((call) => call.url.includes(forbidden)), false, `no ${forbidden} request`);
  }
  window.close();
});

test('the read-only source panel shows model and 360 ontology info', async () => {
  const {root} = await boot();
  root.querySelector('.ak-source-trigger').click();
  await waitFor(() => root.querySelector('.ak-assistant-info'));
  const panel = root.querySelector('.ak-assistant-info');
  assert.match(panel.textContent, /360 全局本体/);
  assert.match(panel.textContent, /团队模型/);
  assert.ok(root.querySelector('button[aria-label="关闭本体库与数据源"]'));
});
