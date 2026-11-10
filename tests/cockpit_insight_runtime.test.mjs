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
const cockpitCss = await readFile(
  new URL('../bi_agent/web/static/cockpit/cockpit.css', import.meta.url),
  'utf8',
);
const combinedInsight = await readFile(
  new URL('../bi_agent/web/static/cockpit/insight-components/sales-shipment-issues/index.js', import.meta.url),
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

test('the stale-scope notice reads as hint text instead of a warning banner', () => {
  const rule = cockpitCss.match(/\.insight-scope-notice\{[^}]*\}/)?.[0] || '';
  const prefix = cockpitCss.match(/\.insight-scope-notice::before\{[^}]*\}/)?.[0] || '';

  assert.match(rule, /color:var\(--cockpit-text-help\)/);
  assert.match(rule, /background:none/);
  assert.match(rule, /border:0/);
  assert.doesNotMatch(rule, /--cockpit-warning/);
  assert.match(prefix, /content:"ⓘ"/);
  assert.match(prefix, /margin-right:6px/);
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

test('risk labels always show a count and keep the last known value for incomplete scopes', () => {
  assert.match(cockpit, /const riskMetricCounts = new Map\(\);/);
  assert.match(cockpit, /function applyRiskCounts\(value\) \{/);
  assert.match(cockpit, /if\(item\.known===true&&current\)\{\s*riskMetricCounts\.set\(metric,count\);/);
  assert.match(cockpit, /else if\(!riskMetricCounts\.has\(metric\)&&item\.complete===true\)\{\s*riskMetricCounts\.set\(metric,count\);/);
  assert.match(cockpit, /if\(!Number\.isFinite\(count\)\)continue;/);
  assert.match(cockpit, /const label=`\$\{count\}条风险`;/);
  assert.doesNotMatch(cockpit, /风险分析中/);
});

test('penetration combined card reads the same deduplicated risk counts as the header', () => {
  assert.match(cockpit, /riskCounts:\s*aiPublicationStore\.riskCounts/);
  assert.match(cockpit, /aiPublicationStore\.riskCounts=next/);
  assert.match(combinedInsight, /props\.slotProps\?\.riskCounts/);
  assert.match(combinedInsight, /销售额风险/);
  assert.match(combinedInsight, /出货量风险/);
  assert.match(combinedInsight, /重点风险 · \{\{ riskFindings\.length \}\} 项/);
  assert.match(combinedInsight, /原因与待核实项 · \{\{ displayCauses\.length \}\} 项/);
  assert.doesNotMatch(combinedInsight, /风险与待核实原因 · \{\{ displayCauses\.length \}\}/);
});

test('risk panels render individual findings instead of reducing them to summary', async () => {
  const shared = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/shared.js', import.meta.url), 'utf8');
  assert.match(shared, /findings = computed\(\(\) => \(result.value\?\.findings \|\| \[\]\)\.slice\(0,4\)\)/);
  assert.match(shared, /v-for="\(finding,index\) in findings"/);
  assert.match(shared, /finding\.title/);
  assert.match(shared, /finding\.description/);
});
