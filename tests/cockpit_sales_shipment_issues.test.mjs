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
  assert.match(source, /<number-text :text="summary" \/>/);
  assert.match(source, /【\{\{ dimension\.stageLabel \}\}】/);
});

test('combined analysis highlights every number with the prototype blue token', () => {
  assert.match(source, /const NUMBER_TOKEN = \/\\d\[\\d,\]\*\(\?:\\\.\\d\+\)\?\(\?:\\\/\\d\+\)\?/);
  assert.match(source, /亿元\|个百分点\|GWh\|个\|%\|天/);
  assert.match(source, /function highlightNumbers/);
  assert.match(source, /<number-text v-if="dimension\.title !== dimension\.stageLabel" :text="dimension\.title" \/>/);
  assert.match(source, /<number-text :text="dimension\.description" \/>/);
  assert.match(source, /<span class="sales-shipment-issues__num">\{\{ index\+1 \}\}<\/span>）/);
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
