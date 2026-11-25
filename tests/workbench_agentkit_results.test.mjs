// TDD RED: result extraction for the AgentKit workbench right pane.
//
// The backend puts results on the tool_result event itself
// (`table` / `chart` / `multi_chart` / `ontology_entities`), not inside
// `output`.  These pure adapters turn that wire shape into board cards,
// evidence rows and subgraph requests (spec §4.2).
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  chartModel,
  evidenceItems,
  ontologyHits,
  subgraphRequest,
  tableModel,
  turnBoardItems,
} from '../frontend/agentkit/results.js';
import {applyEvent, boardItems, createWorkbenchState, startTurn} from '../frontend/agentkit/state.js';

function stateWith(event) {
  let state = startTurn(createWorkbenchState(), {text: 'PACK 未签单商机', sessionId: 's-1'});
  state = applyEvent(state, {type: 'tool_start', turn_id: 't-1', id: 'tool-1', name: 'TableGenerate'});
  return applyEvent(state, {type: 'tool_result', turn_id: 't-1', id: 'tool-1', name: 'TableGenerate', ...event});
}

test('table spec keeps column labels and row order', () => {
  const model = tableModel({
    title: 'PACK 未签单商机明细',
    columns: [{key: 'customer', label: '客户'}, {key: 'gap', label: '缺口（台）'}],
    rows: [['宁德时代', 3], ['比亚迪', 5]],
    summary: '共 2 家客户',
  });
  assert.equal(model.kind, 'table');
  assert.equal(model.title, 'PACK 未签单商机明细');
  assert.deepEqual(model.columns, ['客户', '缺口（台）']);
  assert.deepEqual(model.rows, [['宁德时代', 3], ['比亚迪', 5]]);
  assert.equal(model.summary, '共 2 家客户');
});

test('chart spec maps ECharts options to categories and series', () => {
  const bar = chartModel({
    title: '客户缺口',
    chart_type: 'bar',
    option: {
      xAxis: {data: ['宁德时代', '比亚迪']},
      series: [{name: '缺口', type: 'bar', data: [3, 5]}],
    },
  });
  assert.equal(bar.kind, 'chart');
  assert.equal(bar.chartType, 'bar');
  assert.deepEqual(bar.categories, ['宁德时代', '比亚迪']);
  assert.deepEqual(bar.series, [{name: '缺口', values: [3, 5]}]);

  const pie = chartModel({
    title: '产品部构成',
    chart_type: 'pie',
    option: {series: [{name: '占比', data: [{name: 'PACK', value: 62}, {name: '储能', value: 38}]}]},
  });
  assert.equal(pie.chartType, 'pie');
  assert.deepEqual(pie.slices, [{name: 'PACK', value: 62}, {name: '储能', value: 38}]);
});

test('multi_chart drill-down keeps every dimension on one card', () => {
  let state = startTurn(createWorkbenchState(), {text: '对比', sessionId: 's-1'});
  state = applyEvent(state, {type: 'tool_start', turn_id: 't-1', id: 'tool-9', name: 'ChartGenerateMultiDim'});
  state = applyEvent(state, {
    type: 'tool_result', turn_id: 't-1', id: 'tool-9', name: 'ChartGenerateMultiDim',
    // Real payload: one object with a dimensions list, not a list of specs.
    multi_chart: {
      title: 'PACK 缺口按维度',
      default_dim: 'product_dept',
      summary: '按产品部看缺口',
      dimensions: [
        {
          key: 'customer', label: '客户', chart_type: 'bar',
          option: {xAxis: {data: ['宁德时代']}, series: [{name: '缺口', data: [3]}]},
        },
        {
          key: 'product_dept', label: '产品部', chart_type: 'bar',
          option: {xAxis: {data: ['PACK']}, series: [{name: '缺口', data: [5]}]},
        },
      ],
    },
  });
  const items = boardItems(state);
  assert.equal(items.length, 1);
  assert.equal(items[0].chartType, 'multi');
  assert.deepEqual(items[0].dimensions.map((dim) => dim.key), ['customer', 'product_dept']);
  assert.equal(items[0].defaultKey, 'product_dept');
  assert.deepEqual(items[0].dimensions[1].chart.categories, ['PACK']);
  assert.deepEqual(items[0].dimensions[1].chart.series[0].values, [5]);
});

test('board items read the event-level table, not only output', () => {
  const state = stateWith({
    table: {title: '缺口明细', columns: [{key: 'customer', label: '客户'}], rows: [['宁德时代']]},
    duration_ms: 42,
    ontology_entities: [{code: 'BO_PACK_OPP_002', kind: 'business_object', name: 'PACK 商机'}],
  });
  const items = boardItems(state);
  assert.equal(items.length, 1);
  assert.equal(items[0].kind, 'table');
  assert.equal(items[0].title, '缺口明细');
});

test('ontology hits dedupe by code and keep library plus anchor', () => {
  let state = stateWith({
    ontology_entities: [
      {code: 'MET_PACK_GAP_001', kind: 'metric', name: 'PACK 缺口', repository_id: 'repo-1'},
      {code: 'MET_PACK_GAP_001', kind: 'metric', name: 'PACK 缺口', repository_id: 'repo-1'},
      {code: 'BO_PACK_OPP_002', kind: 'business_object', name: 'PACK 商机', repository_id: 'repo-1'},
    ],
  });
  state = applyEvent(state, {
    type: 'tool_result', turn_id: 't-1', id: 'tool-2', name: 'Ontology-SemanticQuery',
    ontology_entities: [{code: 'MET_PACK_GAP_001', kind: 'metric', name: 'PACK 缺口', repository_id: 'repo-2'}],
  });
  const hits = ontologyHits(state);
  assert.equal(hits.length, 3);
  assert.equal(hits.filter((hit) => hit.code === 'MET_PACK_GAP_001').length, 2);
  assert.deepEqual(hits[0].library || hits[0].repositoryId, 'repo-1');
});

test('evidence rows expose tool, duration, hits and failures', () => {
  const state = stateWith({
    table: {columns: [{key: 'a', label: 'A'}], rows: [[1]]},
    duration_ms: 87,
    ontology_entities: [{code: 'M-1', kind: 'metric', name: '指标'}],
  });
  const rows = evidenceItems(state);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].tool, 'TableGenerate');
  assert.equal(rows[0].durationMs, 87);
  assert.equal(rows[0].hitCount, 1);
  assert.equal(rows[0].status, 'ok');
});

test('subgraph requests are built only for valid ontology codes', () => {
  const request = subgraphRequest(
    {code: 'MET_PACK_GAP_001', kind: 'metric', repositoryId: 'repo-1'},
    's-1',
  );
  assert.deepEqual(request, {
    code: 'MET_PACK_GAP_001',
    type: 'metric',
    strategy: 'context',
    session_id: 's-1',
    repository_id: 'repo-1',
  });
  assert.equal(subgraphRequest({code: 'bad code!'}, 's-1'), null);
  assert.equal(subgraphRequest({code: ''}, 's-1'), null);
});

test('missing chart values stay missing instead of rendering as zero', () => {
  const model = chartModel({
    title: '缺口',
    chart_type: 'bar',
    option: {
      xAxis: {data: ['宁德时代', '比亚迪', '未识别']},
      series: [{name: '缺口', data: [3, null, undefined]}],
    },
  });
  assert.deepEqual(model.series[0].values, [3, null, null]);

  const pie = chartModel({
    title: '构成',
    chart_type: 'pie',
    option: {series: [{name: '占比', data: [{name: 'PACK', value: 62}, {name: '储能', value: null}]}]},
  });
  assert.deepEqual(pie.slices, [{name: 'PACK', value: 62}, {name: '储能', value: null}]);
});

test('each turn keeps its own board items', () => {
  let state = startTurn(createWorkbenchState(), {text: '第一轮', sessionId: 's-1'});
  state = applyEvent(state, {type: 'tool_start', turn_id: 't-1', id: 'tool-1', name: 'TableGenerate'});
  state = applyEvent(state, {type: 'tool_result', turn_id: 't-1', id: 'tool-1', name: 'TableGenerate',
    table: {title: '第一轮明细', columns: [{key: 'a', label: 'A'}], rows: [[1]]}});
  state = applyEvent(state, {type: 'done', turn_id: 't-1'});

  state = startTurn(state, {text: '第二轮', sessionId: 's-1'});
  state = applyEvent(state, {type: 'tool_start', turn_id: 't-2', id: 'tool-2', name: 'ChartGenerate'});
  state = applyEvent(state, {type: 'tool_result', turn_id: 't-2', id: 'tool-2', name: 'ChartGenerate',
    chart: {title: '第二轮图', chart_type: 'bar', option: {xAxis: {data: ['A']}, series: [{name: 'S', data: [2]}]}}});
  state = applyEvent(state, {type: 'done', turn_id: 't-2'});

  assert.deepEqual(turnBoardItems(state.turns[0]).map((item) => item.title), ['第一轮明细']);
  assert.deepEqual(turnBoardItems(state.turns[1]).map((item) => item.title), ['第二轮图']);
});
