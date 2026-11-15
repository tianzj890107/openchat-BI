import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const read = path => readFile(new URL(`../${path}`, import.meta.url), 'utf8');

const MONTHS = Array.from({length: 12}, (_, index) => {
  const month = String(index + 1).padStart(2, '0');
  return {label: `2025-${month}`, value: `2025-${month}`};
});

const assertFilter = filter => {
  assert.equal(filter.dataConfig.sourceType, 'mock');
  assert.deepEqual(filter.baseConfig.defaultValue, {values: {YWLN_D044: '2025-10'}});
  assert.deepEqual(filter.baseConfig.nonClearableDimensions, []);
  const mock = filter.dataConfig.mockData;
  assert.deepEqual(mock.filters, [{id: 'YWLN_D044', name: '日期', type: 'date'}]);
  assert.deepEqual(mock.options, MONTHS);
};

test('delivered date filter opens on 2025-10 and offers the twelve 2025 months', async () => {
  const components = JSON.parse(await read('bi_agent/web/static/cockpit/metadata/iba-demo-1021/components.json'));
  assertFilter(components.find(component => component.type === 'composite-filter'));
});

test('generated runtime keeps the same 2025-10 default filter contract', async () => {
  const runtime = JSON.parse(await read('bi_agent/web/static/cockpit/metadata/runtime.json'));
  assertFilter(runtime.dashboard.components.find(component => component.type === 'composite-filter'));
});

test('grain switch swaps the option list between 2025 and its twelve months', async () => {
  const source = await read('bi_agent/web/static/cockpit/cockpit.js');
  assert.match(source, /const PERIOD_FILTER_YEAR = '2025'/);
  assert.match(source, /PERIOD_FILTER_MONTHS = Array\.from\(\{length: 12\}/);
  assert.match(source, /const values = grain === 'MONTH' \? PERIOD_FILTER_MONTHS : \[PERIOD_FILTER_YEAR\]/);
  assert.match(source, /applyPeriodFilterOptions\(runtime\.value\|\|payload,periodGrain\(args\[1\]\)\)/);
  assert.match(source, /applyPeriodFilterOptions\(runtime\.value\|\|payload,grain\)/);
  assert.doesNotMatch(source, /currentMonth/);
});
