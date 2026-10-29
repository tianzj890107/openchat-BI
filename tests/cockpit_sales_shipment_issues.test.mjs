import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../bi_agent/web/static/cockpit/insight-components/sales-shipment-issues/index.js', import.meta.url), 'utf8');

test('sales and shipment card supplies three evidence-bound fallback findings', () => {
  assert.match(source, /const displayCauses = computed/);
  assert.match(source, /sales-shipment-total-gap/);
  assert.match(source, /sales-shipment-amount-gap/);
  assert.match(source, /sales-shipment-dimension-gap/);
  assert.match(source, /v-for="\(cause, index\) in displayCauses"/);
});
