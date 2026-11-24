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

function stubFetch(window) {
  const calls = [];
  window.fetch = async (url, options = {}) => {
    calls.push({url: String(url), method: options.method || 'GET'});
    const body = String(url).includes('api/conversations')
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

async function boot() {
  const template = await readFile(TEMPLATE, 'utf8');
  const dom = new JSDOM(renderTemplate(template), {
    url: 'http://localhost/workbench-agentkit?source=v61-cockpit&anchor=PACK_OPP_COVERAGE&period=2026Q3',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const {window} = dom;
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
  const calls = stubFetch(window);
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
