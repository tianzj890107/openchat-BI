// Host contract: a risk card opens /workbench-agentkit with the same context
// the page parses.  Runs the documented example in jsdom and checks the round
// trip through parseHandoff, so host and workbench cannot drift apart.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {dirname, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

import {parseHandoff} from '../frontend/agentkit/state.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');
const frontendRequire = createRequire(resolve(ROOT, 'frontend/package.json'));
const {JSDOM} = frontendRequire('jsdom');

test('the host example opens the workbench with a valid handoff', async () => {
  const html = await readFile(resolve(ROOT, 'docs/examples/agentkit-host-handoff.html'), 'utf8');
  const dom = new JSDOM(html, {
    url: 'http://localhost/cockpit/index.html',
    runScripts: 'dangerously',
  });
  const {window} = dom;
  window.document.querySelector('[data-open-workbench]').click();

  const url = window.__agentkitHandoffUrl;
  assert.ok(url, 'the card produced a workbench URL');
  assert.match(url, /^\/api\/ontology-agentic-analytics\/workbench-agentkit\?/);

  const handoff = parseHandoff(url.slice(url.indexOf('?')));
  assert.equal(handoff.active, true);
  assert.equal(handoff.invalid, false);
  assert.equal(handoff.anchor, 'PACK_OPP_COVERAGE');
  assert.equal(handoff.period, '2026Q3');
  assert.deepEqual(handoff.filters, {customer: '宁德时代', region: '华东'});
  assert.deepEqual(handoff.evidence, ['ev-11', 'ev-12']);
  assert.equal(handoff.handoffId, 'h-7');
});
