import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../frontend/', import.meta.url));
const {JSDOM} = require('jsdom');

const bundle = await readFile(new URL('../bi_agent/web/static/vendor/agentkit/workbench-agentkit-embed.js', import.meta.url), 'utf8');

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
  };
}

function jsonResponse(body) {
  return {ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body)};
}

async function waitFor(predicate, timeout = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const value = predicate();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('timeout waiting for DOM');
}

async function boot({view = 'chat'} = {}) {
  const dom = new JSDOM('<!doctype html><html><body><div id="chuxiaoce-root" data-a360="assistant"></div></body></html>', {
    url: `https://cockpit.example/app/workbench-agentkit?a360=assistant&view=${view}`,
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const {window} = dom;
  for (const key of ['TransformStream', 'ReadableStream', 'TextEncoder', 'TextDecoder', 'MessageChannel', 'MessagePort']) {
    if (globalThis[key] && !window[key]) window[key] = globalThis[key];
  }
  window.ResizeObserver ||= class { observe() {} unobserve() {} disconnect() {} };
  window.matchMedia ||= () => ({matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}});
  window.scrollTo ||= () => {};
  window.APP_ROOT_PATH = '/app';
  const calls = [];
  window.fetch = async (url, init = {}) => {
    calls.push({url: String(url), init});
    if (String(url).includes('api/meta')) {
      return jsonResponse({agent: {model: '团队模型 · 深度分析'}});
    }
    if (String(url).includes('api/analysis360/chat')) {
      return sseResponse([
        {type: 'sop_progress', step: 1, detail: '识别经营问题'},
        {type: 'text_delta', text: '先看商机覆盖。'},
        {type: 'done', turn_id: 't1'},
      ]);
    }
    return jsonResponse({});
  };
  window.eval(bundle);
  const root = window.document.getElementById('chuxiaoce-root');
  await waitFor(() => (view === 'board' ? root.querySelector('.ak-board-inner') : root.querySelector('.ak-empty-title')));
  return {dom, window, root, calls};
}

test('the embedded assistant greets 储小策 and sends the 360 direct chat request', async () => {
  const {root, calls, window} = await boot();
  assert.match(root.textContent, /储小策，我帮你/);
  assert.match(root.textContent, /看目标 · 看差距 · 看趋势/);
  const suggestion = [...root.querySelectorAll('.ak-suggestions button')][0];
  assert.ok(suggestion, 'welcome suggestions are rendered');
  suggestion.click();
  await waitFor(() => calls.some((call) => call.url.includes('api/analysis360/chat')));
  const chat = calls.find((call) => call.url.includes('api/analysis360/chat'));
  const body = JSON.parse(chat.init.body);
  assert.equal(body.analysis360_direct, true);
  assert.ok(body.session_id.startsWith('a360-'));
  assert.equal(chat.url, '/app/api/analysis360/chat');
  await waitFor(() => root.querySelector('.ak-transcript')?.textContent.includes('先看商机覆盖。'));
  // The 360 run is now visible in the history rail.
  assert.match(root.querySelector('.ak-embed-sessions')?.textContent || '', /商机覆盖|分析/);
  window.close();
});

test('opening with view=board renders the conversation board with the same session', async () => {
  const {root, calls} = await boot({view: 'board'});
  const embed = root.querySelector('.ak-embed');
  assert.equal(embed.dataset.view, 'board');
  assert.ok(root.querySelector('.ak-board-inner'), 'the AgentKit board renders');
  assert.match(root.textContent, /返回主页/);
  assert.ok(embed.dataset.session.startsWith('a360-'), 'the 360 session id is kept for the board view');
  assert.equal(calls.filter((call) => call.url.includes('api/analysis360/chat')).length, 0,
    'opening the board does not send a new question');
  root.ownerDocument.defaultView.close();
});
