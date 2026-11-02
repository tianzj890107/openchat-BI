import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const cockpit = await readFile(
  new URL('../bi_agent/web/static/cockpit/cockpit.js', import.meta.url),
  'utf8',
);
const html = await readFile(
  new URL('../bi_agent/web/static/cockpit/index.html', import.meta.url),
  'utf8',
);

test('AI insight slots receive the current page without referencing an outer setup ref', () => {
  const start = cockpit.indexOf('const CockpitInsight = {');
  const end = cockpit.indexOf('\n  function canonical', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const component = cockpit.slice(start, end);

  assert.match(component, /page:\s*\{type:\s*String,\s*default:\s*'overview'\}/);
  assert.match(component, /page:\s*props\.page/);
  assert.doesNotMatch(component, /page:\s*page\.value/);
  assert.match(html, /<cockpit-insight[^>]*:page="page"/);
});

test('a broken delivered insight leaves loading and shows an explicit error', () => {
  assert.match(cockpit, /onErrorCaptured\(\(cause, _instance, info\) => \{/)
  assert.match(cockpit, /componentError\.value = `AI 卡片渲染失败/)
  assert.match(cockpit, /delivered\.value = null/)
  assert.match(cockpit, /v-else-if="insightLoadError \|\| componentError"/)
});

test('every AI slot renders the shared stale-scope notice', () => {
  assert.match(cockpit, /v-if="state\.scopeNotice" class="insight-scope-notice"/)
  assert.match(cockpit, /:scope-notice="state\.scopeNotice \|\| ''"/)
});

test('risk count labels bind the dashboard runtime explicitly and never reach into setup refs', () => {
  const start = cockpit.indexOf('function syncRiskCountLabels(');
  const end = cockpit.indexOf('\n  function hasPublishedSlot', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const sync = cockpit.slice(start, end);

  assert.match(cockpit, /function syncRiskCountLabels\(runtime\) \{/);
  assert.doesNotMatch(sync, /biRuntime\.value/);
  assert.doesNotMatch(cockpit, /syncRiskCountLabels\(\)/);
  assert.match(cockpit, /function bindRiskCountRuntime\(runtime\) \{/);
  assert.match(cockpit, /function syncBoundRiskCountLabels\(\) \{/);
  assert.match(cockpit, /function unbindRiskCountRuntime\(runtime\) \{/);
  assert.match(cockpit, /syncBoundRiskCountLabels\(\);\s*\n\s*settleMissingSlotStages\(\)/);
  assert.equal((cockpit.match(/[\s;]bindRiskCountRuntime\(biRuntime\.value\)/g) || []).length, 3);
  assert.match(cockpit, /onBeforeUnmount\(\(\) => \{unbindRiskCountRuntime\(biRuntime\.value\);/);
});
