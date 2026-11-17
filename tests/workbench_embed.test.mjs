import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import { handoffSendMode } from '../bi_agent/web/static/analysis360-handoff.mjs';
import { isComposerSendKey, takeComposerText } from '../frontend/src/composerInput.js';

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
