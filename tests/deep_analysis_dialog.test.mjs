import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  promptFor, splitSSEFrames, reduceStream, markdownLite,
} from '../bi_agent/web/static/cockpit/insight-components/deep-analysis/model.js';

const read = path => readFile(new URL(path, import.meta.url), 'utf8');

test('the dialog prompt names the root cause it opens with', () => {
  assert.equal(promptFor({title: '供应链交期延迟'}), '深度分析「供应链交期延迟」根因');
  assert.equal(promptFor({causeCode: 'RC09'}), '深度分析「RC09」根因');
  assert.equal(promptFor(null), '深度分析这条根因');
});

test('SSE frames split across chunks keep the trailing partial frame', () => {
  const first = splitSSEFrames('data: {"type":"text_delta","text":"定位"}\n\ndata: {"type":"text_delta","te');
  assert.deepEqual(first.events, [{type: 'text_delta', text: '定位'}]);
  assert.equal(first.rest, 'data: {"type":"text_delta","te');
  const second = splitSSEFrames(`${first.rest}xt":"根因"}\n\n`);
  assert.deepEqual(second.events, [{type: 'text_delta', text: '根因'}]);
  assert.equal(second.rest, '');
});

test('malformed frames are skipped instead of breaking the stream', () => {
  const {events, rest} = splitSSEFrames('data: not-json\n\ndata: {"type":"done"}\n\n');
  assert.deepEqual(events, [{type: 'done'}]);
  assert.equal(rest, '');
});

test('stream events accumulate the answer and surface choices', () => {
  let state = {text: '', activity: '', busy: true, error: '', choices: null};
  for (const event of [
    {type: 'tool_use', name: 'G360ResolveScope'},
    {type: 'text_delta', text: '先在全局本体中定位'},
    {type: 'text_delta', text: '这条根因。'},
    {type: 'tool_result'},
    {type: 'user_choice_requested', question: '是否下钻根因？', options: [{id: 'drill', label: '下钻根因'}]},
  ]) {
    state = reduceStream(state, event)
  }
  assert.equal(state.text, '先在全局本体中定位这条根因。');
  assert.equal(state.activity, '');
  assert.equal(state.busy, false);
  assert.deepEqual(state.choices, {question: '是否下钻根因？', options: [{id: 'drill', label: '下钻根因'}]});
});

test('errors keep the streamed text and stop the turn', () => {
  let state = {text: '已取到的部分', activity: '', busy: true, error: '', choices: null};
  state = reduceStream(state, {type: 'error', message: '360 智能分析未配置'});
  assert.equal(state.text, '已取到的部分');
  assert.equal(state.error, '360 智能分析未配置');
  assert.equal(state.busy, false);
  state = reduceStream(state, {type: 'session_superseded'});
  assert.match(state.error, /重新点击/);
});

test('model markdown is escaped before a small set of rules is applied', () => {
  const html = markdownLite('### 结论\n- 交期 <script>alert(1)</script> 超过 12 天\n1. **核实** `D044` 明细');
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('<h4>结论</h4>'));
  assert.ok(html.includes('<li>交期 &lt;script&gt;alert(1)&lt;/script&gt; 超过 12 天</li>'));
  assert.ok(html.includes('<strong>核实</strong>'));
  assert.ok(html.includes('<code>D044</code>'));
});

test('the cockpit card opens the in-place dialog for every cause row', async () => {
  const shared = await read('../bi_agent/web/static/cockpit/insight-components/shared.js');
  const dialog = await read('../bi_agent/web/static/cockpit/insight-components/deep-analysis/dialog.js');
  // Entry exists on both cause layouts (nested under a risk and the flat 原因 section).
  assert.equal((shared.match(/class="stage-risk-analysis__deep"/g) || []).length, 2);
  assert.match(shared, /openCauseDeepAnalysis\(dimension\)/);
  assert.match(shared, /<deep-analysis-dialog v-if="deepAnalysis"/);
  // The dialog talks to the 360-only endpoints and prefills the root cause.
  assert.match(dialog, /\/api\/analysis360\/handoff/);
  assert.match(dialog, /\/api\/analysis360\/chat/);
  assert.match(dialog, /\/api\/analysis360\/choice/);
  // The new-tab helper may stay for other surfaces, but no entry calls it.
  assert.ok(!/await openDeepAnalysis\(/.test(shared), 'no new-tab deep analysis entry should remain');
});
