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
  assert.match(shared, /<number-text :text="summary" \/>/);
  assert.match(shared, /<number-text :text="finding\.description" \/>/);
  assert.match(shared, /<number-text :text="item\.action" \/>/);
  assert.match(shared, /stage-risk-analysis__owner/);
  assert.match(shared, /displayOwnerRole/);
  assert.match(shared, /\(\?:牵头\|协同\|配合\|支持\|执行\|负责\)/);
  assert.match(shared, /String\(item\?\.deadline/);
  assert.match(css, /\.stage-risk-analysis__owner\{/);
  assert.match(css, /\.stage-risk-analysis__num\{color:var\(--cockpit-primary\);font-weight:600\}/);
});
