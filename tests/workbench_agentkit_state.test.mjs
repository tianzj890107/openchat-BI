// TDD RED: the AgentKit workbench projects the analysis SSE stream onto one
// conversation state: one turn at a time, tool calls merged in place, stale
// turns ignored, clarification pauses the turn, and stopping never produces a
// second terminal result (spec §2, §4.1).
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  applyEvent,
  boardItems,
  buildHandoffUrl,
  createWorkbenchState,
  parseHandoff,
  startTurn,
  stopTurn,
} from '../frontend/agentkit/state.js';

function streaming(extra = {}) {
  let state = createWorkbenchState();
  state = startTurn(state, {text: 'PACK 未签单商机主要涉及哪些客户？', sessionId: 's-1'});
  return {...state, ...extra};
}

test('parseHandoff reads the V6.1 card context', () => {
  const handoff = parseHandoff(
    '?source=v61-cockpit&anchor=PACK_OPP_COVERAGE&period=2026Q3'
    + '&filters=customer%3D%E5%AE%81%E5%BE%B7%E6%97%B6%E4%BB%A3%3Bregion%3D%E5%8D%8E%E4%B8%9C'
    + '&evidence=ev-11,ev-12&handoff=h-7',
  );
  assert.equal(handoff.active, true);
  assert.equal(handoff.invalid, false);
  assert.equal(handoff.source, 'v61-cockpit');
  assert.equal(handoff.anchor, 'PACK_OPP_COVERAGE');
  assert.equal(handoff.period, '2026Q3');
  assert.deepEqual(handoff.filters, {customer: '宁德时代', region: '华东'});
  assert.deepEqual(handoff.evidence, ['ev-11', 'ev-12']);
  assert.equal(handoff.handoffId, 'h-7');
  assert.match(handoff.summary, /PACK_OPP_COVERAGE/);
  assert.match(handoff.summary, /2026Q3/);
});

test('parseHandoff flags a broken handoff instead of silently dropping it', () => {
  const broken = parseHandoff('?handoff=h-9&source=v61-cockpit');
  assert.equal(broken.active, true);
  assert.equal(broken.invalid, true);
  assert.match(broken.reason, /anchors?|锚点/i);

  const empty = parseHandoff('');
  assert.equal(empty.active, false);
  assert.equal(empty.invalid, false);
});

test('a new turn owns the state until a terminal event arrives', () => {
  const state = streaming();
  assert.equal(state.status, 'streaming');
  assert.equal(state.turns.length, 1);
  const turn = state.turns[0];
  assert.equal(turn.user, 'PACK 未签单商机主要涉及哪些客户？');
  assert.equal(turn.assistant.text, '');
  assert.equal(turn.assistant.tools.length, 0);
});

test('stream deltas append to the same assistant message', () => {
  let state = streaming();
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: 'PACK 未签单'});
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: '商机涉及 12 家客户。'});
  const turn = state.turns[0];
  assert.equal(turn.assistant.text, 'PACK 未签单商机涉及 12 家客户。');
  assert.equal(state.activeTurnId, 't-1');
});

test('tool events merge into one call, and duplicate results are ignored', () => {
  let state = streaming();
  // The backend emits tool_start / tool_input / tool_result with a full input.
  state = applyEvent(state, {type: 'tool_start', turn_id: 't-1', id: 'tool-1', name: 'query_ontology'});
  state = applyEvent(state, {
    type: 'tool_input', turn_id: 't-1', id: 'tool-1', input: '{"anchor":"pack"}',
  });
  state = applyEvent(state, {
    type: 'tool_result', turn_id: 't-1', id: 'tool-1', name: 'query_ontology',
    input: '{"anchor":"pack"}',
    output: {table: {columns: ['customer', 'gap'], rows: [['宁德时代', 3]]}},
    ontology_entities: [{code: 'BO-PACK', type: 'business_object'}],
  });
  state = applyEvent(state, {
    type: 'tool_result', turn_id: 't-1', id: 'tool-1',
    output: {table: {columns: ['customer', 'gap'], rows: [['宁德时代', 3]]}},
  });
  const tools = state.turns[0].assistant.tools;
  assert.equal(tools.length, 1);
  assert.equal(tools[0].status, 'done');
  assert.equal(tools[0].input, '{"anchor":"pack"}');
  assert.equal(tools[0].entities[0].code, 'BO-PACK');
  assert.equal(boardItems(state).length, 1);
});

test('clarification pauses the turn and keeps the placeholder', () => {
  let state = streaming();
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: '需要确认统计期间。'});
  state = applyEvent(state, {
    type: 'user_choice_requested', turn_id: 't-1', tool_use_id: 'tool-1',
    question: '统计期间', options: [{id: 'q3', label: '2026Q3'}],
  });
  assert.equal(state.status, 'paused');
  assert.equal(state.pendingChoice.options.length, 1);
  assert.equal(state.turns[0].assistant.text, '需要确认统计期间。');
});

test('late events from an older turn never touch the current interface', () => {
  let state = streaming();
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: '第一轮'});
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-2', text: '迟到的第二轮'});
  assert.equal(state.turns[0].assistant.text, '第一轮');
  assert.equal(state.status, 'streaming');
});

test('done is terminal exactly once', () => {
  let state = streaming();
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: '结论'});
  state = applyEvent(state, {type: 'done', turn_id: 't-1'});
  const finished = JSON.parse(JSON.stringify(state));
  state = applyEvent(state, {type: 'done', turn_id: 't-1'});
  assert.equal(state.status, 'idle');
  assert.deepEqual(JSON.parse(JSON.stringify(state)), finished);
});

test('stopping keeps partial text and reports an interrupt once', () => {
  let state = streaming();
  state = applyEvent(state, {type: 'text_delta', turn_id: 't-1', text: '部分结论'});
  state = stopTurn(state);
  assert.equal(state.status, 'interrupted');
  assert.equal(state.turns[0].assistant.text, '部分结论');
  state = applyEvent(state, {type: 'done', turn_id: 't-1'});
  assert.equal(state.status, 'interrupted');
});

test('errors keep prior results visible and expose a retry handle', () => {
  let state = streaming();
  state = applyEvent(state, {
    type: 'tool_result', turn_id: 't-1', tool_use_id: 'tool-1',
    output: {table: {columns: ['a'], rows: [[1]]}},
  });
  state = applyEvent(state, {type: 'error', turn_id: 't-1', message: '取数失败'});
  assert.equal(state.status, 'error');
  assert.match(state.error, /取数失败/);
  assert.equal(boardItems(state).length, 1);
});

test('buildHandoffUrl round-trips the card context through parseHandoff', () => {
  const url = buildHandoffUrl(
    {
      source: 'v61-cockpit',
      anchor: 'PACK_OPP_COVERAGE',
      period: '2026Q3',
      filters: {customer: '宁德时代', region: '华东'},
      evidence: ['ev-11', 'ev-12'],
      handoffId: 'h-7',
    },
    '/api/ontology-agentic-analytics',
  );
  assert.match(url, /^\/api\/ontology-agentic-analytics\/workbench-agentkit\?/);
  assert.match(url, /anchor=PACK_OPP_COVERAGE/);
  const parsed = parseHandoff(url.slice(url.indexOf('?')));
  assert.equal(parsed.active, true);
  assert.equal(parsed.invalid, false);
  assert.equal(parsed.anchor, 'PACK_OPP_COVERAGE');
  assert.equal(parsed.period, '2026Q3');
  assert.deepEqual(parsed.filters, {customer: '宁德时代', region: '华东'});
  assert.deepEqual(parsed.evidence, ['ev-11', 'ev-12']);
  assert.equal(parsed.handoffId, 'h-7');
});

test('assistant-ui adapter projects turns into thread messages', async () => {
  const {toThreadMessages, textFromAppend} = await import('../frontend/agentkit/messageAdapter.js');
  const turns = [
    {id: 'turn-1', user: 'PACK 缺口', status: 'done', assistant: {
      text: '共 2 家客户', thinking: '', tools: [{id: 'tool-1', name: 'TableGenerate', status: 'done'}],
    }},
  ];
  const messages = toThreadMessages(turns);
  assert.equal(messages.length, 2);
  assert.equal(messages[0].role, 'user');
  assert.deepEqual(messages[0].content, [{type: 'text', text: 'PACK 缺口'}]);
  assert.equal(messages[1].role, 'assistant');
  assert.equal(messages[1].content[0].text, '共 2 家客户');
  assert.equal(messages[1].metadata.custom.tools[0].name, 'TableGenerate');

  assert.equal(textFromAppend({content: [{type: 'text', text: ' 继续 '}]}), '继续');
  assert.equal(textFromAppend({content: [{type: 'text', text: '你好'}, {type: 'image'}]}), '你好');
  assert.equal(textFromAppend({content: []}), '');
});

test('the runtime module declares its assistant-ui adapter identity', async () => {
  const {AGENTKIT_RUNTIME} = await import('../frontend/agentkit/messageAdapter.js');
  assert.match(AGENTKIT_RUNTIME, /assistant-ui/);
});
