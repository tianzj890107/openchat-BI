import test from 'node:test';
import assert from 'node:assert/strict';
import {selectSlotAnalysis} from '../bi_agent/web/static/cockpit/publication-selection.js';

const payload = (id, updatedAt, slotId = 'opportunity-risk') => ({
  id, updatedAt, context: {slotId}, result: {summary: id},
});
const published = value => ({status: 'ready', payload: value});

test('independent card ignores a newer shared opportunity result', () => {
  const shared = payload('shared-newer', 200, 'opportunity');
  const independent = payload('independent-older', 100);
  assert.equal(selectSlotAnalysis({
    slotId: 'opportunity-risk', independent: true,
    published: published(independent), current: shared,
  }).id, 'independent-older');
});

test('independent card stays correct when its own publication arrives later', () => {
  const shared = payload('shared-older', 100, 'opportunity');
  const independent = payload('independent-newer', 200);
  assert.equal(selectSlotAnalysis({
    slotId: 'opportunity-risk', independent: true,
    published: published(independent), current: shared,
  }).id, 'independent-newer');
});

test('independent card never falls back to a shared-stage item without its slot id', () => {
  assert.equal(selectSlotAnalysis({
    slotId: 'opportunity-risk', independent: true,
    published: {status: 'missing'}, current: payload('shared', 200, 'opportunity'),
  }), null);
});

test('ordinary slots keep the previous timestamp comparison', () => {
  const older = payload('older', 100, 'order');
  const newer = payload('newer', 200, 'order');
  assert.equal(selectSlotAnalysis({
    slotId: 'order-risk-summary', independent: false,
    published: published(newer), current: older,
  }).id, 'newer');
});
