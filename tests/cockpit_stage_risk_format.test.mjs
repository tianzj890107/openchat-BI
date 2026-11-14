import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {highlightNumbers} from '../bi_agent/web/static/cockpit/insight-components/number-highlight.js';

test('risk card highlights numbers and their units as one blue token', () => {
  assert.deepEqual(highlightNumbers('缺口 127.6 亿元，达成率 60.0%，周期 26.73 天'), [
    {text: '缺口 ', num: false},
    {text: '127.6 亿元', num: true},
    {text: '，达成率 ', num: false},
    {text: '60.0%', num: true},
    {text: '，周期 ', num: false},
    {text: '26.73 天', num: true},
  ]);
});

test('shared stage risk component highlights text and keeps the display owner role', async () => {
  const shared = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/shared.js', import.meta.url), 'utf8');
  const css = await readFile(new URL('../bi_agent/web/static/cockpit/cockpit.css', import.meta.url), 'utf8');
  assert.match(shared, /<number-text :text="riskSummary" \/>/);
  assert.match(shared, /<number-text :text="finding\.description" \/>/);
  assert.match(shared, /<number-text :text="item\.action" \/>/);
  assert.match(shared, /stage-risk-analysis__owner/);
  assert.match(shared, /displayOwnerRole/);
  assert.match(shared, /建议角色/);
  assert.match(shared, /\(\?:牵头\|协同\|配合\|支持\|执行\|负责\)/);
  assert.match(shared, /String\(item\?\.deadline/);
  assert.match(shared, /stage-risk-analysis__ontology/);
  assert.match(shared, /ontologyTrace/);
  assert.match(shared, /distinctEvidenceCount/);
  assert.match(shared, /traceFor/);
  assert.match(shared, /识别的规则/);
  assert.match(shared, /命中的本体/);
  assert.match(shared, /取数 SQL/);
  assert.match(shared, /ruleName/);
  assert.match(shared, /rulesOntology/);
  assert.match(shared, /成立条件/);
  assert.match(css, /\.stage-risk-analysis__owner\{/);
  assert.match(css, /\.stage-risk-analysis__owner\{[^}]*color:var\(--cockpit-primary\)/);
  assert.match(css, /\.stage-risk-analysis__ontology\{/);
  assert.match(css, /\.stage-risk-analysis__trace-query pre\{/);
  assert.match(css, /\.stage-risk-analysis__num\{color:var\(--cockpit-primary\);font-weight:600\}/);
  assert.match(shared, /durationText/);
  assert.match(shared, /query\.executionId/);
  assert.match(shared, /query\.resultHash/);
  assert.match(shared, /query\.sampleRows/);
  assert.match(shared, /汇总口径/);
  assert.match(shared, /返回数据/);
  assert.match(css, /\.stage-risk-analysis__trace-meta\{/);
  assert.match(css, /\.stage-risk-analysis__trace-table\{/);
});

test('a card section opens with the summary of its own displayed items when the card keeps them', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/shared.js', import.meta.url), 'utf8');
  // No fallback: without its own summary a section shows none.
  assert.match(source, /riskSummary = computed\(\(\) => \(findings\.value\.length && sectionSummaries\.value\.riskSummary\) \|\| ''\)/);
  // The 商机获取 card turns them off (sectionSummaries: false) and lists rows only.
  assert.match(source, /<div v-if="showSectionSummaries && riskSummary" class="stage-risk-analysis__summary"/);
  // Every established risk is shown, and the ontology display lists every judgement.
  assert.match(source, /const findings = computed\(\(\) => result\.value\?\.findings \|\| \[\]\)/);
  assert.doesNotMatch(source, /findings \|\| \[\]\)\.slice\(0,\s*4\)/);
  assert.match(source, /本体判定明细/);
  assert.match(source, /v-for="item in group\.items"/);
  assert.match(source, /<div v-if="showSectionSummaries && causeSummary" class="stage-risk-analysis__summary"/);
  assert.match(source, /<div v-if="showSectionSummaries && adviceSummary" class="stage-risk-analysis__summary"/);
});

test('rule-first risks show how each one was decided', async () => {
  const source = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/shared.js', import.meta.url), 'utf8');
  assert.match(source, /finding\.decidedBy === 'rule' \? '规则判定' : '模型判定'/);
  // The judgement list is its own expandable section, titled with hit counts.
  assert.match(source, /<details v-if="judgementGroups\.length" class="stage-risk-analysis__foot stage-risk-analysis__judgement">/);
  assert.match(source, /\{\{ group\.title \}\}命中 \{\{ group\.hit \}\}\/\{\{ group\.items\.length \}\}/);
});
