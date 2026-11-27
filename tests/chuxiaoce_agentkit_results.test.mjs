import test from 'node:test';
import assert from 'node:assert/strict';

import {turnBoardItems, toolBoardItems} from '../frontend/agentkit/results.js';

const evidence = {
  status: 'ok', evidenceId: 'E3', queryKey: 'opp_coverage', rowCount: 120, previewRows: 3,
  columns: ['customer', 'weighted_amount', 'gap'],
  rows: [
    {customer: '宁德时代', weighted_amount: 1200, gap: 300},
    {customer: '比亚迪', weighted_amount: 980, gap: 260},
    {customer: '亿纬锂能', weighted_amount: 640, gap: 120},
  ],
  queryStatus: 'validated',
};

test('a 360 evidence payload becomes one board table card', () => {
  const tool = {id: 't1', name: 'G360Query', status: 'done', output: JSON.stringify(evidence)};
  const items = toolBoardItems(tool);
  assert.equal(items.length, 1);
  const [card] = items;
  assert.equal(card.kind, 'table');
  assert.deepEqual(card.columns, ['customer', 'weighted_amount', 'gap']);
  assert.equal(card.rows.length, 3);
  assert.match(card.summary, /120 行/);
  assert.match(card.summary, /预览 3 行/);
  assert.match(card.summary, /证据 E3/);
  const turn = {id: 'turn-1', assistant: {text: '', tools: [tool]}};
  assert.equal(turnBoardItems(turn).length, 1);
});

test('rows given as arrays still map to the declared columns', () => {
  const tool = {id: 't2', name: 'G360Query', status: 'done',
    output: JSON.stringify({columns: ['a', 'b'], rows: [[1, 2], [3, 4]], rowCount: 2})};
  const [card] = toolBoardItems(tool);
  assert.deepEqual(card.rows, [[1, 2], [3, 4]]);
});

test('a native table spec wins and is not duplicated by the 360 adapter', () => {
  const tool = {id: 't3', name: 'x', status: 'done',
    table: {columns: [{key: 'a', label: 'A'}], rows: [{a: 1}]},
    output: JSON.stringify({columns: ['a'], rows: [{a: 1}]})};
  const items = toolBoardItems(tool);
  assert.equal(items.length, 1);
  assert.equal(items[0].id, 't3:table');
});
