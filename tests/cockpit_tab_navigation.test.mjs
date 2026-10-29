import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(
  new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),
  'utf8',
);

test('top tabs navigate with history instead of reloading the document', () => {
  assert.doesNotMatch(source, /location\.assign\(routeFor/);
  assert.doesNotMatch(source, /location\.reload\(/);
  assert.match(source, /history\.pushState\(\{cockpitPage: target\}/);
  assert.match(source, /window\.addEventListener\('popstate', onPopState\)/);
  assert.match(source, /goPage\(entry\[0\]\)/);
});

test('tab switching keeps the mounted board and only re-points page state', () => {
  const start = source.indexOf('switchPageImpl=async target=>{');
  assert.notEqual(start, -1);
  const end = source.indexOf('\n            };', start);
  assert.notEqual(end, -1);
  const block = source.slice(start, end);
  // Reinstalling a fresh data client here recreates the SDK data scope and
  // loses the cache of every visited tab.
  assert.doesNotMatch(block, /install\(null/);
  assert.doesNotMatch(block, /currentUiScope='default'/);
  assert.match(block, /pageCache=createPageCache/);
  assert.match(block, /publications\?\.preload\(started\.cards/);
  assert.match(block, /for\(const stage of stagesForPage\(target\)\)ensureAnalysis/);
});
