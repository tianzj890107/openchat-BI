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
  // 商机本体 1117 BR-V01: three one-sentence lines (商机 / 订单 / 发货) replace the overall line and the rows.
  assert.match(source, /stageLines: true/);
  assert.match(source, /showOverallSummary: false/);
  assert.match(shared, /\[\['商机', '商机问题'\], \['订单', '订单问题'\], \['发货', '订未发问题'\]\]/);
  assert.match(shared, /<p v-for="line in stageLines" :key="line.label" class="stage-risk-analysis__stage-line"><b>\{\{ line.label \}\}<\/b>：/);
  assert.match(source, /showCauses: false/);
  assert.match(source, /showRecommendations: false/);
  assert.doesNotMatch(opportunity, /primaryLabel/);
});

test('the combined card is titled 销售额与出货量共同分析 and groups problems by stage', () => {
  assert.match(source, /headTitle: '销售额与出货量共同分析'/);
  assert.match(source, /fallbackStage: '销售额与出货量共同分析'/);
  // Parent groups carry their own summaries, like the 销售额口径明细 cards.
  assert.match(source, /sectionSummaries: false/);
  assert.match(shared, /\{\{ headTitle \|\| \(displayStage \+ '当前' \+ primaryLabel \+ '判断'\) \}\}/);
  assert.match(shared, /v-for="group in \(stageLinesMode \? \[\] : riskGroups\)"/);
  assert.doesNotMatch(source, /指标异常|数据问题/);
});

test('problem-only cards hide cause, advice and their judgement groups', () => {
  assert.match(shared, /const showCauses = options\.showCauses !== false/);
  assert.match(shared, /const showRecommendations = options\.showRecommendations !== false/);
  assert.match(shared, /v-if="showCauses && !causesUnderRisks && analysisDimensions\.length"/);
  assert.match(shared, /v-if="showRecommendations && recommendations\.length"/);
  // Evidence lists only the rule and the SQL; the matched ontology is gone.
  assert.match(shared, /识别的规则/);
  assert.match(shared, /取数 SQL/);
  assert.doesNotMatch(shared, /命中的本体/);
  assert.match(shared, /<template v-if="showCauses">成立\{\{ primaryLabel \}\}若没有命中任何本体根因/);
  assert.match(shared, /group\.kind === 'causes' && showCauses/);
  assert.match(shared, /group\.kind === 'advice' && showRecommendations/);
});

test('the shared card words its first layer by the primary label', () => {
  assert.match(shared, /const primaryLabel = options\.primaryLabel \|\| '风险'/);
  assert.match(shared, /【\{\{ primaryLabel \}\}】/);
  assert.match(shared, /'当前' \+ primaryLabel \+ '判断'/);
  assert.match(shared, /\{\{ primaryLabel \}\}\{\{ number \}\}/);
  assert.match(shared, /\{\{ primaryLabel \}\}规则 \{\{ ontologyTrace\.risks\.length \}\} 条/);
  assert.match(shared, /<template v-if="finding\.issueType">【\{\{ plain\(finding\.issueType\) \}\}】<\/template>/);
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

test('the 商机获取 card nests each risk\'s causes under it and hides advice', () => {
  // One risk → many causes: an expandable list under every risk row.
  assert.match(opportunity, /causesUnderRisks: true/);
  assert.match(opportunity, /showRecommendations: false/);
  assert.match(shared, /<details v-if="causesUnderRisks && causesFor\(finding\)\.length" class="stage-risk-analysis__risk-causes" :open="causesOpen">/);
  assert.match(shared, /\{\{ causesFor\(finding\)\.length \}\} 项根因/);
  assert.match(shared, /v-for="\(dimension, causeIndex\) in causesFor\(finding\)"/);
  // A cause shared by two risks is listed under both.
  assert.match(shared, /for \(const id of new Set\(dimension\.findingIds \|\| \[\]\)\)/);
  // The nested list carries no "风险N—原因M" cross reference.
  const nested = shared.slice(shared.indexOf('stage-risk-analysis__risk-causes"'), shared.indexOf('</details>', shared.indexOf('stage-risk-analysis__risk-causes"')));
  assert.doesNotMatch(nested, /riskLinks/);
  // Hidden advice also drops its acceptance lines from the footer.
  assert.match(shared, /in \(showRecommendations \? openRecommendations : \[\]\)/);
  // Causes from the AI global analysis are labelled as such, not as an ontology miss.
  assert.equal((shared.match(/dimension\.analysis === 'ai' \? '（AI 分析 · 待核实）'/g) || []).length, 2);
  // Risk and cause evidence share one component.
  assert.equal((shared.match(/<trace-details /g) || []).length, 3);
  // 1117 BR-V02～V05 on the 商机获取 card: titles, no group summary row, causes open, evidence hidden.
  assert.match(opportunity, /headTitle: '商机当前风险判断及根因分析'/);
  assert.match(opportunity, /groupTitleSuffix: '及根因分析'/);
  assert.match(opportunity, /groupSummaries: false/);
  assert.match(opportunity, /causesOpen: true/);
  assert.match(opportunity, /showEvidence: false/);
  assert.match(shared, /\{\{ group\.category \}\}\{\{ groupTitleSuffix \}\}/);
  assert.match(shared, /'stage-risk-analysis__risk-group--strong': groupTitleSuffix/);
  assert.match(shared, /<p v-if="showGroupSummaries && group\.summary"/);
  assert.equal((shared.match(/<trace-details v-if="showEvidence" /g) || []).length, 2);
  assert.match(shared, /name: 'StageTraceDetails'/);
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
