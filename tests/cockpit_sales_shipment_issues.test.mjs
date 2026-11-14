import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/sales-shipment-issues/index.js', import.meta.url), 'utf8');

const shared = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/shared.js', import.meta.url), 'utf8');
const opportunity = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/opportunity-risk/index.js', import.meta.url), 'utf8');

test('the combined card is problem driven on the stage card layout', () => {
  // 指标 → 问题 (not 指标 → 风险): the same layout as the stage cards, worded as problems.
  assert.match(source, /createStageRiskComponent\(\{/);
  assert.match(source, /primaryLabel: '问题'/);
  assert.match(source, /showOverallSummary: true/);
  assert.doesNotMatch(opportunity, /primaryLabel/);
});

test('the shared card words its first layer by the primary label', () => {
  assert.match(shared, /const primaryLabel = options\.primaryLabel \|\| '风险'/);
  assert.match(shared, /【\{\{ primaryLabel \}\}】/);
  assert.match(shared, /当前\{\{ primaryLabel \}\}判断/);
  assert.match(shared, /\{\{ primaryLabel \}\}\{\{ index\+1 \}\}/);
  assert.match(shared, /\{\{ primaryLabel \}\}规则 \{\{ ontologyTrace\.risks\.length \}\} 条/);
  assert.match(shared, /<template v-if="finding\.issueType">【\{\{ finding\.issueType \}\}】<\/template>/);
  assert.match(shared, /label:`\$\{primaryLabel\}\$\{riskIndex\.get\(id\)\}—原因\$\{analysisNumber\}`/);
  assert.doesNotMatch(shared, /【风险】/);
  assert.match(shared, /data:'数据质量'/);
});

test('evidence lists only the queries behind the item when queries name their metrics', () => {
  assert.match(shared, /query\.metricCodes\.some\(code => metrics\.has\(code\)\)/);
  assert.match(shared, /!Array\.isArray\(query\.metricCodes\)/);
});

test('combined analysis uses the prototype typography and divider', async () => {
  const css = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/sales-shipment-issues/index.css', import.meta.url), 'utf8');
  assert.match(css, /font-size:\s*13\.5px/);
  assert.match(css, /line-height:\s*1\.85/);
  assert.match(css, /font-size:\s*14px/);
  assert.match(css, /font-weight:\s*700/);
  assert.match(css, /border-top:\s*1px solid var\(--cockpit-divider,\s*#eaebf2\)/);
  assert.match(css, /color:\s*var\(--cockpit-text,\s*rgba\(0,\s*0,\s*0,\s*\.85\)\)/);
  assert.match(css, /\.sales-shipment-issues__num\s*\{[^}]*color:\s*var\(--cockpit-primary,\s*#165dff\)/s);
  assert.match(css, /\.sales-shipment-issues__num\s*\{[^}]*font-weight:\s*600/s);
});

test('the 商机获取 card shows its rows only, without per-section summaries', () => {
  assert.match(opportunity, /sectionSummaries: false/);
  assert.match(shared, /const showSectionSummaries = options\.sectionSummaries !== false/);
  for (const name of ['riskSummary', 'causeSummary', 'adviceSummary']) {
    assert.ok(shared.includes(`v-if="showSectionSummaries && ${name}"`), name);
  }
});

test('evidence SQL is the queries the server linked to that very item', () => {
  assert.match(shared, /Array\.isArray\(item\?\.queryIds\)\s*\?\s*queryCatalog\.value\.filter\(query => item\.queryIds\.includes\(query\.executionId\)\)/);
});
