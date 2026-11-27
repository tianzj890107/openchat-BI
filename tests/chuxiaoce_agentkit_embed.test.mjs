import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const assistantSource = await read('../bi_agent/web/static/cockpit/assistant.js');
const embedEntry = await read('../frontend/agentkit/embed.jsx');
const bridge = await import('../frontend/agentkit/embedBridge.js');
const assistant = await import('../bi_agent/web/static/cockpit/assistant.js');

test('the cockpit opens the AgentKit assistant page at the existing /workbench entry', () => {
  assert.match(assistantSource, /\/workbench\?a360=assistant/);
  assert.match(assistantSource, /^export const ASSISTANT_PATH = '\/workbench\?a360=assistant'/m);
  });

test('the first open carries the host view and later switches reuse the frame', async () => {
  assert.equal(bridge.assistantUrl('/app', 'board'), '/app/workbench?a360=assistant&view=board');
  assert.equal(bridge.assistantUrl('', 'chat'), '/workbench?a360=assistant&view=chat');
  assert.equal(bridge.initialView('?a360=assistant&view=board'), 'board');
  assert.equal(bridge.initialView('?a360=assistant'), 'chat');
  assert.equal(bridge.initialView('?a360=assistant&view=chat'), 'chat');
});

test('host and child exchange only validated messages', () => {
  const origin = 'https://cockpit.example';
  const win = {name: 'frame'};
  assert.deepEqual(
    bridge.readHostView({origin, source: win, data: {source: 'cockpit-assistant', type: 'view', view: 'board'}}, origin, win),
    'board',
  );
  assert.equal(bridge.readHostView({origin: 'https://evil.example', source: win,
    data: {source: 'cockpit-assistant', type: 'view', view: 'board'}}, origin, win), null);
  assert.equal(bridge.readHostView({origin, source: {}, data: {source: 'cockpit-assistant', type: 'view', view: 'board'}}, origin, win), null);
  assert.equal(bridge.readHostView({origin, source: win, data: {source: 'x', type: 'view', view: 'board'}}, origin, win), null);
  assert.equal(bridge.readHostView({origin, source: win, data: {source: 'cockpit-assistant', type: 'view', view: 'closed'}}, origin, win), null);
  assert.equal(bridge.isReady({origin, source: win, data: {source: 'cockpit-assistant', type: 'ready'}}, origin, win), true);
  assert.equal(bridge.isReady({origin, source: win, data: {source: 'cockpit-assistant', type: 'ready'}}, origin, {}), false);
});

test('the child requests home, board and close with the shared envelope', () => {
  assert.deepEqual(bridge.requestMessage('home'), {source: 'cockpit-assistant', type: 'request', request: 'home'});
  assert.deepEqual(bridge.requestMessage('board'), {source: 'cockpit-assistant', type: 'request', request: 'board'});
  assert.deepEqual(bridge.requestMessage('close'), {source: 'cockpit-assistant', type: 'request', request: 'close'});
  assert.deepEqual(bridge.viewMessage('board'), {source: 'cockpit-assistant', type: 'view', view: 'board'});
});

test('session restore survives collapse, reopen and refresh', () => {
  const store = new Map();
  const storage = {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
  };
  const first = bridge.resumeSession(storage, () => 'a360-fixed-1');
  assert.equal(first, 'a360-fixed-1');
  assert.equal(bridge.resumeSession(storage, () => 'never'), 'a360-fixed-1');
  bridge.rememberSession(storage, 'a360-fixed-1');
  assert.equal(bridge.readCurrentSession(storage), 'a360-fixed-1');
});

test('the embedded app talks to the 360 endpoints and keeps the host view', () => {
  assert.match(embedEntry, /api\/analysis360\/chat/);
  assert.match(embedEntry, /analysis360_direct: true|analysis360_direct:true/);
  assert.match(embedEntry, /api\/analysis360\/choice/);
  assert.match(embedEntry, /postRequest\("home"\)/);
  assert.match(embedEntry, /postRequest\("board"\)/);
  assert.match(embedEntry, /postRequest\("close"\)/);
  assert.match(embedEntry, /requestMessage/);
  assert.match(embedEntry, /readHostView/);
  assert.match(embedEntry, /储小策/);
});
