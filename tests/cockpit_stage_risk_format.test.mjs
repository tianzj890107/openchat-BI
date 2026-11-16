import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {highlightNumbers, stripOntologyCodes} from '../bi_agent/web/static/cockpit/insight-components/number-highlight.js';

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
  assert.doesNotMatch(shared, /命中的本体/);
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

test('card text hides ontology codes and keeps the wording', () => {
  const cases = [
    ['RK01 商机预测覆盖不足', '商机预测覆盖不足'],
    ['RK02 签单进度滞后（已签单覆盖率口径）', '签单进度滞后（已签单覆盖率口径）'],
    ['未签单预测金额 12.35 亿元；按 BR-Q02 订单关联口径判断。', '未签单预测金额 12.35 亿元；按订单关联口径判断。'],
    ['均值 50% 及以上（R13）；小环节缺少完成事件', '均值 50% 及以上；小环节缺少完成事件'],
    ['客户等级 1 为战略客户（本体 DR04）', '客户等级 1 为战略客户'],
    ['BR-Q01：所选年度内同商机同月取最新一版', '所选年度内同商机同月取最新一版'],
    ['R12–R17 阶段周期分档', '阶段周期分档'],
    ['依据 IS01 指标异常与 DQ02 数据问题', '依据指标异常与数据问题'],
    ['B01-AMOUNT 目标金额 120.50 亿元', '目标金额 120.50 亿元'],
    ['RC03 需求确认未落实，AC07 逐户补齐', '需求确认未落实，逐户补齐'],
    // Business wording that looks code-like stays.
    ['P0 阶段 4 条商机，P2 超期', 'P0 阶段 4 条商机，P2 超期'],
    ['型号 LF280K 与 MB31 电芯', '型号 LF280K 与 MB31 电芯'],
    ['2025-10 期间落后 42.0 个百分点', '2025-10 期间落后 42.0 个百分点'],
  ];
  for (const [input, expected] of cases) assert.equal(stripOntologyCodes(input), expected, input);
});

test('risk, cause and advice cards render text through the code filter', async () => {
  const dir = '../bi_agent/web/static/cockpit/insight-components/';
  const read = path => readFile(new URL(dir + path, import.meta.url), 'utf8');
  const shared = await read('shared.js');
  assert.match(shared, /parts\(\) \{ return highlightNumbers\(stripOntologyCodes\(this\.text\)\) \}/);
  assert.match(shared, /const summary = computed\(\(\) => stripOntologyCodes\(/);
  assert.match(shared, /\{\{ plain\(finding\.title\) \}\}/);
  assert.match(shared, /plain\(dimension\.title\)/);
  assert.match(shared, /<b>\{\{ metric\.stage \}\}阶段<\/b>/);
  assert.doesNotMatch(shared, /\{\{ metric\.code \}\}/);
  assert.match(await read('bid-summary/index.js'), /\{\{ plain\(cause\.title\) \}\}/);
  assert.match(await read('opportunity-coverage-note/index.js'), /plain\(cause\.description\)/);
});
