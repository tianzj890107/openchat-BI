import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/sales-shipment-issues/index.js', import.meta.url), 'utf8');

test('sales and shipment card renders only the prototype summary and numbered business dimensions', () => {
  assert.doesNotMatch(source, /sales-shipment-total-gap/);
  assert.doesNotMatch(source, /sales-shipment-amount-gap/);
  assert.doesNotMatch(source, /sales-shipment-dimension-gap/);
  assert.doesNotMatch(source, /status: 'hypothesis'/);
  assert.match(source, /v-for="\(dimension,index\) in analysisDimensions"/);
  assert.doesNotMatch(source, /props\.slotProps\?\.riskCounts/);
  assert.doesNotMatch(source, /销售额重点风险/);
  assert.doesNotMatch(source, /出货量重点风险/);
  assert.doesNotMatch(source, /重点风险 ·/);
  assert.doesNotMatch(source, /原因分析 ·/);
  assert.doesNotMatch(source, /建议 ·/);
  assert.doesNotMatch(source, /数据范围与限制/);
  assert.doesNotMatch(source, /查看完整证据/);
  assert.match(source, /销售额／出货量共同问题分析：/);
  assert.match(source, /\{\{ summary \}\}/);
  assert.match(source, /【\{\{ dimension\.stageLabel \}\}】/);
});
