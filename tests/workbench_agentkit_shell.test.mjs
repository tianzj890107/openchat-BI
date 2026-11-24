// TDD RED: the AgentKit workbench page shell, theme scope and upstream import
// trail.  The page is built from this repo (frontend/agentkit) and served from
// its own asset directory, so the legacy Pro UI workbench keeps its bundle
// (spec §2, §2.1, §5).
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {dirname, resolve} from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const read = (relative) => readFile(resolve(ROOT, relative), 'utf8');
const exists = async (relative) => {
  try {
    await stat(resolve(ROOT, relative));
    return true;
  } catch {
    return false;
  }
};

test('the page shell owns sessions, thread, board and handoff regions', async () => {
  const html = await read('bi_agent/web/static/agentkit/index.html');
  assert.match(html, /id="agentkit-root"/);
  assert.match(html, /data-agentkit-root/);
  for (const region of ['sessions', 'thread', 'board', 'handoff']) {
    assert.match(html, new RegExp(`data-agentkit-${region}`), `missing ${region} region`);
  }
  assert.match(html, /data-agentkit-layout-toggle/, 'narrow screens switch between thread and board');
  assert.match(html, /\.\.\/static\/vendor\/agentkit\/workbench-agentkit\.css|@@APP_ROOT_PATH@@\/static\/vendor\/agentkit\/workbench-agentkit\.css/);
  assert.match(html, /workbench-agentkit\.js\?v=@@AGENTKIT_JS_VERSION@@/);
});

test('the AgentKit theme is scoped and never leaks into the legacy page', async () => {
  const source = await read('frontend/agentkit/agentkit-theme.css');
  assert.match(source, /\.ak-shell/);
  assert.match(source, /--ak-bg/);
  assert.match(source, /--ak-accent/);
  // Wide layout keeps three panes; narrow switches thread/board instead of stacking.
  assert.match(source, /@media \(max-width: 960px\)/);
  // Theme variables live on the workbench scope, not the global root.
  assert.ok(!/^\s*:root\s*\{[^}]*--ak-/m.test(source), 'theme tokens must not be declared on :root');

  // The built stylesheet keeps the same scope (minified selectors unchanged).
  const built = await read('bi_agent/web/static/vendor/agentkit/workbench-agentkit.css');
  assert.match(built, /\.ak-shell\{/);
  assert.match(built, /@media\(max-width:960px\)/);
});

test('the committed AgentKit bundle is built from this repo', async () => {
  const js = await read('bi_agent/web/static/vendor/agentkit/workbench-agentkit.js');
  assert.ok(js.length > 1000);
  assert.match(js, /agentkit-root/);
  assert.match(js, /ak-shell/);
  // One conversation state module, imported by the app entry.
  const state = await read('frontend/agentkit/state.js');
  assert.match(state, /export function applyEvent/);
  assert.match(state, /export function parseHandoff/);
});

test('the AgentKit app builds from frontend/agentkit with its own config', async () => {
  const config = await read('frontend/vite.agentkit.config.js');
  assert.match(config, /agentkit\/main\.jsx/);
  assert.match(config, /static\/vendor\/agentkit/);
  assert.match(config, /workbench-agentkit\.js/);
  assert.ok(await exists('frontend/agentkit/main.jsx'));
  assert.ok(await exists('frontend/agentkit/App.jsx'));
});

test('the upstream import keeps the pinned commit and file list on record', async () => {
  const upstream = await read('frontend/agentkit/UPSTREAM.md');
  assert.match(upstream, /b8df86dfa3c30de6676cd1d768cda504bf3c3338/);
  assert.match(upstream, /agentkit-ui\/public\/r\/aui-thread\.json/);
  assert.match(upstream, /agentkit-ui\/src\/components\/assistant-ui\/elements\//);
  const script = await read('scripts/import_agentkit_upstream.py');
  assert.match(script, /get-tar-commit-id/);
  assert.match(script, /b8df86dfa3c30de6676cd1d768cda504bf3c3338/);
});
