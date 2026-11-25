// Chat request shape: the question is visible, the card scope travels beside
// it so the backend can re-check the scope (spec §3.2, §4.1).
import test from 'node:test';
import assert from 'node:assert/strict';

import {buildChatBody, openConversation, saveConversation} from '../frontend/agentkit/api.js';

test('a card scope is carried in the chat body, never in the visible text', () => {
  const body = buildChatBody({
    message: 'PACK 未签单商机主要涉及哪些客户？',
    visibleText: 'PACK 未签单商机主要涉及哪些客户？',
    sessionId: 'agentkit-h-7',
    scope: {
      source: 'v61-cockpit',
      anchor: 'PACK_OPP_COVERAGE',
      period: '2026Q3',
      filters: {customer: '宁德时代'},
      evidence: ['ev-11'],
      handoff_id: 'h-7',
    },
  });
  assert.equal(body.message, 'PACK 未签单商机主要涉及哪些客户？');
  assert.equal(body.visible_user_text, 'PACK 未签单商机主要涉及哪些客户？');
  assert.equal(body.session_id, 'agentkit-h-7');
  assert.deepEqual(body.scope, {
    source: 'v61-cockpit',
    anchor: 'PACK_OPP_COVERAGE',
    period: '2026Q3',
    filters: {customer: '宁德时代'},
    evidence: ['ev-11'],
    handoff_id: 'h-7',
  });
});

test('a free question sends no scope field', () => {
  const body = buildChatBody({message: '你好', sessionId: 's-1'});
  assert.equal(body.message, '你好');
  assert.equal(body.visible_user_text, '你好');
  assert.equal('scope' in body, false);
});

test('opening a conversation passes the session and returns the snapshot', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url: String(url), method: options.method, body: options.body});
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({
        session_id: 'agentkit-restore',
        messages: [{role: 'user', content: [{type: 'text', text: 'PACK 缺口'}]}],
        agentkit: {version: 1, turns: [{id: 'turn-1', user: 'PACK 缺口', assistant: {text: '共 2 家', tools: []}}]},
      }),
    };
  };
  try {
    const restored = await openConversation('conv-1', 'agentkit-old');
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/conversations\/conv-1\/activate\?unified=true&session_id=agentkit-old$/);
    assert.equal(calls[0].method, 'POST');
    assert.equal(restored.sessionId, 'agentkit-restore');
    assert.equal(restored.messages.length, 1);
    assert.equal(restored.agentkit.turns[0].assistant.text, '共 2 家');
  } finally {
    globalThis.fetch = original;
  }
});

test('saving a conversation sends the structured turns', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({url: String(url), body: JSON.parse(options.body || '{}')});
    return {ok: true, status: 200, text: async () => JSON.stringify({id: 'conv-9'})};
  };
  try {
    const result = await saveConversation({
      sessionId: 'agentkit-1',
      cid: 'conv-9',
      title: 'PACK 缺口',
      turns: [{id: 'turn-1', user: 'PACK 缺口', assistant: {text: '共 2 家', tools: []}}],
    });
    assert.equal(result.cid, 'conv-9');
    assert.equal(calls[0].body.session_id, 'agentkit-1');
    assert.equal(calls[0].body.mode, 'data');
    assert.equal(calls[0].body.agentkit.turns[0].id, 'turn-1');
    assert.equal(calls[0].body.agentkit.version, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test('report mode uses its own chat, choice and save routes and EOF is not a success', async () => {
  const {streamChat, chooseOption, saveConversation} = await import('../frontend/agentkit/api.js');
  const calls = [];
  const events = [];
  const fetchBefore = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push([url, JSON.parse(options.body)]);
    return url.includes('/save')
      ? new Response('{"id":"report-history"}')
      : new Response('data: {"type":"text_delta","text":"部分结果"}\n\n');
  };
  try {
    await streamChat({mode:'report', sessionId:'r1', message:'报表问题', onEvent:event => events.push(event)});
    await chooseOption({mode:'report', sessionId:'r1', ids:['manual:上期'], labels:['上期'], onEvent:() => {}});
    await saveConversation({mode:'report', sessionId:'r1'});
    assert.deepEqual(calls.map(([url]) => url), ['/api/report/chat','/api/report/choice','/api/conversations/save']);
    assert.equal(calls[2][1].mode, 'report');
    assert.equal(events.at(-1).type, 'stream_interrupted');
  } finally { globalThis.fetch = fetchBefore; }
});
