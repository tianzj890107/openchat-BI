import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { handoffSendMode } from '../bi_agent/web/static/analysis360-handoff.mjs';
import { isComposerSendKey, takeComposerText, shouldPersistConversation } from '../frontend/src/composerInput.js';
import { consumePrefill, isComposerReady, markComposerGone, markComposerReady, queuePrefill, resetHandshake } from '../frontend/src/composerHandshake.js';

const read = path => readFile(new URL(path, import.meta.url), 'utf8');

test('the existing workbench page keeps auto-sending, the root-cause embed waits for the user', () => {
  assert.equal(handoffSendMode('?a360=abc'), 'auto');
  assert.equal(handoffSendMode('?a360=abc&send=1'), 'auto');
  assert.equal(handoffSendMode('?a360=abc&send=0'), 'manual');
  assert.equal(handoffSendMode('?embed=rootcause&a360=abc&send=0'), 'manual');
  assert.equal(handoffSendMode(''), 'auto');
});

test('the composer clears before the request, every turn', () => {
  const input = {value: '  深度分析「交期延迟」根因  '};
  assert.equal(takeComposerText(input), '深度分析「交期延迟」根因');
  assert.equal(input.value, '', 'the text is taken out of the box immediately');
  assert.equal(takeComposerText(input), '', 'an empty box never sends');
  assert.equal(takeComposerText({value: '   '}), '');
});

test('Enter sends only in the composer, never during IME composition', () => {
  assert.equal(isComposerSendKey({key: 'Enter', shiftKey: false}), true);
  assert.equal(isComposerSendKey({key: 'Enter', shiftKey: true}), false);
  assert.equal(isComposerSendKey({key: 'Enter', shiftKey: false, isComposing: true}), false);
  assert.equal(isComposerSendKey({key: 'Enter', shiftKey: false, keyCode: 229}), false);
  assert.equal(isComposerSendKey({key: 'a', shiftKey: false}), false);
});

test('the workbench composer is wired to the shared helpers', async () => {
  const runtime = await read('../frontend/src/runtime.js');
  assert.match(runtime, /takeComposerText\(el\.chatInput\)/);
  assert.match(runtime, /isComposerSendKey\(e\)/);
  // No second, document-wide Enter-to-send path.
  assert.doesNotMatch(runtime, /document\.addEventListener\("keydown",[^)]*trySend/s);
});

test('the root-cause dialog embeds the real workbench instead of a second chat UI', async () => {
  const dialog = await read('../bi_agent/web/static/cockpit/insight-components/deep-analysis/dialog.js');
  assert.match(dialog, /<iframe/);
  assert.match(dialog, /embed=rootcause/);
  assert.match(dialog, /send=0/);
  // The single-pane composer and its markdown bubbles are gone.
  assert.doesNotMatch(dialog, /deep-analysis-dialog__composer/);
  assert.doesNotMatch(dialog, /markdownLite/);
});

test('the shipment cause breakdown exposes the same entry on its cause groups', async () => {
  const component = await read('../bi_agent/web/static/cockpit/insight-components/shipment-cause-breakdown/index.js');
  assert.match(component, /openCauseDeepAnalysis/);
  assert.match(component, /class="shipment-cause-breakdown__deep"/);
  assert.match(component, /DeepAnalysisDialog/);
});

test('the root-cause embed never writes the temporary conversation into 最近', async () => {
  assert.equal(shouldPersistConversation({embed: 'rootcause'}), false);
  assert.equal(shouldPersistConversation({embed: ''}), true);
  assert.equal(shouldPersistConversation({}), true);
  const runtime = await read('../frontend/src/runtime.js');
  assert.match(runtime, /shouldPersistConversation\(/);
  assert.match(runtime, /function saveCurrentConversation\(options = \{\}\) \{[\s\S]{0,400}?shouldPersistConversation\(/);
});

test('a failed first request still consumes the handoff, so retry keeps the session', async () => {
  const { withHandoff, HANDOFF_FIELD } = await import('../bi_agent/web/static/analysis360-handoff.mjs');
  const bodies = [];
  const fetchImpl = async (url, init) => {
    bodies.push(JSON.parse(init.body));
    throw new Error('stream interrupted');
  };
  const wrapped = withHandoff(fetchImpl, 'handoff-1');
  await wrapped('/app/api/chat', {method: 'POST', body: JSON.stringify({message: 'q1', session_id: 's1'})})
    .catch(() => {});
  await wrapped('/app/api/chat', {method: 'POST', body: JSON.stringify({message: 'retry', session_id: 's1'})})
    .catch(() => {});
  assert.equal(bodies[0][HANDOFF_FIELD], 'handoff-1');
  assert.equal(bodies[1][HANDOFF_FIELD], undefined, 'the retry reuses the accepted session');
});

test('the welcome suggestions cannot be painted over the composer', async () => {
  const css = await read('../frontend/src/workbench.css');
  const block = css.slice(css.indexOf('body.pro-ui-workbench-body .pro-ui-empty-layer {'));
  const rule = block.slice(0, block.indexOf('}'));
  assert.doesNotMatch(rule, /position:\s*absolute/);
  assert.match(rule, /overflow-y:\s*auto/);
  assert.match(rule, /flex:\s*0 0 auto/);
});

test('the handed-over clause reaches the visible controlled composer', async () => {
  const handoff = await read('../bi_agent/web/static/analysis360-handoff.mjs');
  assert.match(handoff, /bi-composer-prefill/);
  assert.match(handoff, /CustomEvent\(\"bi-composer-prefill\"/);
});

test('a prefill that arrives before the visible composer mounts is applied, not lost', () => {
  resetHandshake();
  assert.equal(isComposerReady(), false);
  queuePrefill('深度分析「战略客户需求确认未落实」根因', 'cause-1');
  markComposerReady();
  assert.equal(isComposerReady(), true);
  assert.deepEqual(consumePrefill(), {text: '深度分析「战略客户需求确认未落实」根因', id: 'cause-1'});
  assert.equal(consumePrefill(), null, 'the queue is consumed exactly once');
  queuePrefill('', 'x');
  assert.equal(consumePrefill(), null, 'an empty prefill is ignored');
  markComposerGone();
  assert.equal(isComposerReady(), false);
});

test('the visible composer announces readiness and the runtime empties it with the box', async () => {
  const composer = await read('../frontend/src/ProUiComposer.jsx');
  assert.match(composer, /bi-composer-ready/);
  assert.match(composer, /consumePrefill\(\)/);
  const runtime = await read('../frontend/src/runtime.js');
  assert.match(runtime, /takeComposerText\(el\.chatInput\)[\s\S]{0,200}?dispatchEvent\(new Event\("input"/);
});

test('a failed slot module is retried once with a fresh version instead of breaking the card', async () => {
  const loader = await read('../bi_agent/web/static/cockpit/insight-components/index.js');
  assert.match(loader, /loadWithRetry/);
  assert.match(loader, /searchParams\.set\('v', String\(Date\.now\(\)\)\)/);
});

test('the dialog header is one line and the empty layer never grows a blank band', async () => {
  const dialog = await read('../bi_agent/web/static/cockpit/insight-components/deep-analysis/dialog.js');
  assert.match(dialog, /深度分析 · 根因：\s*<span class="deep-analysis-workbench__name">\{\{ itemTitle \}\}<\/span>/);
  const css = await read('../frontend/src/workbench.css');
  const block = css.slice(css.indexOf('body.pro-ui-workbench-body .pro-ui-empty-layer {'));
  const rule = block.slice(0, block.indexOf('}'));
  assert.match(rule, /flex:\s*0 0 auto/);
  assert.doesNotMatch(rule, /flex:\s*1 1 auto/);
  assert.match(css, /\.pro-ui-empty-layer:empty\s*\{\s*display:\s*none/);
});

test('the root-cause header stays on a single line', async () => {
  const dialog = await read('../bi_agent/web/static/cockpit/insight-components/deep-analysis/dialog.js');
  assert.match(dialog, /deep-analysis-workbench__context-main"[\s\S]{0,200}?title=/);
  assert.match(dialog, /white-space:nowrap;overflow:hidden;text-overflow:ellipsis/);
  assert.doesNotMatch(dialog, /__desc\{margin:0;color:var\(--cockpit-text-secondary/);
});

test('the transcript column can scroll inside the pane', async () => {
  const css = await read('../frontend/src/workbench.css');
  const block = css.slice(css.indexOf('.chat-scroll {'));
  const rule = block.slice(0, block.indexOf('}'));
  assert.match(rule, /min-height:\s*0/);
  assert.match(rule, /overflow-y:\s*auto/);
});
