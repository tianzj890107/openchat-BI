// The restored demo2-era workbench (commit 07ac670) must still boot: this is
// the regression reference behind /workbench-legacy, so a broken bundle would
// silently turn the compatibility entry into a blank page.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const frontendRequire = createRequire(resolve(ROOT, 'frontend/package.json'));
const {JSDOM} = frontendRequire('jsdom');

const TEMPLATE = resolve(ROOT, 'bi_agent/web/static/workbench-legacy/index.html');
const LEGACY_DIR = resolve(ROOT, 'bi_agent/web/static/vendor/antd-legacy');

test('the restored demo2 legacy page mounts its UI', async () => {
  const template = await readFile(TEMPLATE, 'utf8');
  const html = template
    .replaceAll('@@APP_ROOT_PATH@@', '')
    .replace(/<script[^>]*><\/script>/g, '')
    .replace('</head>', '<script>window.APP_ROOT_PATH = "";</script></head>');

  const dom = new JSDOM(html, {
    url: 'http://localhost/workbench-legacy',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const {window} = dom;
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  window.matchMedia = () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
  // The legacy bundle probes WebGL globals while registering chart renderers.
  window.WebGL2RenderingContext = window.WebGL2RenderingContext || class {};
  window.WebGLRenderingContext = window.WebGLRenderingContext || class {};
  for (const name of ['TransformStream', 'ReadableStream', 'WritableStream', 'TextDecoder', 'TextEncoder', 'structuredClone']) {
    if (typeof globalThis[name] !== 'undefined' && typeof window[name] === 'undefined') {
      window[name] = globalThis[name];
    }
  }
  window.fetch = async () => ({
    ok: true,
    status: 200,
    headers: {get: () => null},
    text: async () => JSON.stringify({conversations: [], sources: {}, config: {}}),
    json: async () => ({conversations: [], sources: {}, config: {}}),
  });

  const evalErrors = [];
  for (const file of ['lib/vue.global.js', 'lib/pro-bi-ui.min.js', 'workbench-legacy.js']) {
    const code = await readFile(resolve(LEGACY_DIR, file), 'utf8');
    try {
      window.eval(code);
    } catch (error) {
      evalErrors.push(`${file}: ${error.message}`);
    }
  }
  await new Promise((done) => setTimeout(done, 700));

  assert.deepEqual(evalErrors, [], 'legacy scripts evaluate without throwing');
  const root = window.document.getElementById('root');
  assert.ok(root, 'legacy mount point exists');
  assert.ok((root.innerHTML || '').length > 1000, 'legacy app rendered its shell');
  assert.match(window.document.body.textContent, /新对话/, 'legacy navigation visible');
  assert.match(window.document.body.textContent, /智能分析/, 'legacy brand visible');
});
