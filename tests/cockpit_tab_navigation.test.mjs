import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(
  new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),
  'utf8',
);

test('top tabs navigate with history instead of reloading the document', () => {
  assert.doesNotMatch(source, /location\.assign\(routeFor/);
  const start = source.indexOf('function onTabClick');
  const end = source.indexOf('function onPopState', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  assert.doesNotMatch(source.slice(start, end), /location\.reload\(/);
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
  assert.match(block, /pageCache\.cards\(\)/);
  assert.match(block, /statusPoller\?\.poke\(0\)/);
  assert.match(block, /publications\?\.preload\(cards\.items/);
  assert.match(block, /for\(const stage of stagesForPage\(target\)\)ensureAnalysis/);
});
