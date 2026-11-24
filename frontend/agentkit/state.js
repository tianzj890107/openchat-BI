// Conversation state for the AgentKit workbench.
//
// The analysis backend streams one turn at a time as SSE events.  This module
// projects that stream onto a single conversation state so the page never has
// to reason about event order twice: tool events merge into their call, late
// events from an older turn are dropped, clarification pauses the turn, and
// every terminal event is applied at most once (spec §4.1).
//
// Adapted from AgentKit `thread.aui.tsx` external-store projection.  Pure
// module: no DOM, no fetch — unit-tested by tests/workbench_agentkit_state.test.mjs.

const TERMINAL_EVENTS = new Set(['done', 'error', 'session_superseded', 'stream_interrupted']);

function emptyState() {
  return {
    sessionId: '',
    status: 'idle', // idle | streaming | paused | error | interrupted
    turns: [],
    activeTurnId: null,
    pendingChoice: null,
    error: '',
  };
}

export function createWorkbenchState() {
  return emptyState();
}

function parseFilters(raw) {
  const text = String(raw || '').trim();
  if (!text) return {};
  if (text.startsWith('{')) {
    try {
      const parsed = JSON.parse(text);
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }
  const out = {};
  for (const part of text.split(';')) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    const index = trimmed.indexOf('=');
    if (index < 0) continue;
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim();
    if (key) out[key] = value;
  }
  return out;
}

/**
 * Read the V6.1 handoff context attached to the entry URL.
 *
 * A handoff without an anchor cannot be matched to an ontology code, so it is
 * reported as active-but-invalid instead of silently dropped: the banner then
 * offers "back to the source card" and "start over" (spec §3.2).
 */
export function parseHandoff(search) {
  const params = new URLSearchParams(String(search || '').replace(/^\?/, ''));
  const source = (params.get('source') || '').trim();
  const anchor = (params.get('anchor') || params.get('risk') || '').trim();
  const period = (params.get('period') || '').trim();
  const handoffId = (params.get('handoff') || '').trim();
  const filters = parseFilters(params.get('filters'));
  const evidence = String(params.get('evidence') || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);

  const active = Boolean(handoffId || anchor || source || period);
  const invalid = active && !anchor;
  const reason = invalid ? '交接缺少风险或指标锚点（anchor），无法对齐统计期间与指标口径' : '';
  const summary = active && !invalid
    ? `来源 ${source || '未标注'} · 锚点 ${anchor} · 期间 ${period || '未指定'}`
    : '';

  return {
    active,
    invalid,
    reason,
    summary,
    source,
    anchor,
    period,
    handoffId,
    filters,
    evidence,
  };
}

let turnSeq = 0;

/** Begin a turn: user text lands immediately, the assistant bubble streams in. */
export function startTurn(state, {text, sessionId} = {}) {
  turnSeq += 1;
  const userText = String(text || '').trim();
  return {
    ...state,
    sessionId: sessionId || state.sessionId,
    status: 'streaming',
    error: '',
    pendingChoice: null,
    activeTurnId: null,
    turns: [
      ...state.turns,
      {
        id: `turn-${turnSeq}`,
        user: userText,
        status: 'streaming',
        assistant: {text: '', thinking: '', tools: []},
      },
    ],
  };
}

function currentTurn(state) {
  return state.turns.length ? state.turns[state.turns.length - 1] : null;
}

function updateTurn(state, patch) {
  const turn = currentTurn(state);
  if (!turn) return state;
  return {...state, turns: [...state.turns.slice(0, -1), {...turn, ...patch}]};
}

function updateAssistant(state, patch) {
  const turn = currentTurn(state);
  if (!turn) return state;
  return updateTurn(state, {assistant: {...turn.assistant, ...patch}});
}

function updateTools(state, mutator) {
  const turn = currentTurn(state);
  if (!turn) return state;
  return updateAssistant(state, {tools: mutator(turn.assistant.tools)});
}

function addBoardItemIfAny(tool) {
  return boardItemFromTool(tool) ? tool : tool;
}

/** Extract one renderable result from a tool output, when it carries one. */
export function boardItemFromTool(tool) {
  const output = tool && tool.output;
  if (!output || typeof output !== 'object') return null;
  const title = tool.title || tool.name || '分析结果';
  if (output.table && Array.isArray(output.table.rows)) {
    return {
      id: tool.id,
      kind: 'table',
      title: output.table.title || title,
      columns: Array.isArray(output.table.columns) ? output.table.columns : [],
      rows: output.table.rows,
    };
  }
  if (output.chart && Array.isArray(output.chart.series)) {
    return {id: tool.id, kind: 'chart', title: output.chart.title || title, chart: output.chart};
  }
  if (output.metric && typeof output.metric.value !== 'undefined') {
    return {id: tool.id, kind: 'metric', title: output.metric.title || title, metric: output.metric};
  }
  return null;
}

/** Right-pane results: one item per tool call, later results replace earlier ones. */
export function boardItems(state) {
  const items = [];
  const seen = new Set();
  for (const turn of state.turns || []) {
    for (const tool of turn.assistant?.tools || []) {
      const item = boardItemFromTool(tool);
      if (!item || seen.has(item.id)) continue;
      seen.add(item.id);
      items.push(item);
    }
  }
  return items;
}

/**
 * Fold one SSE event into the conversation state.
 *
 * Returns the same object when the event is stale or already applied, so React
 * does not re-render on duplicate terminal frames.
 */
export function applyEvent(state, event) {
  if (!event || typeof event !== 'object') return state;
  const type = String(event.type || '');
  if (!type) return state;

  if (event.turn_id) {
    if (state.activeTurnId && event.turn_id !== state.activeTurnId) return state;
    state = {...state, activeTurnId: event.turn_id};
  }

  // A stopped or failed turn is closed: a late terminal frame must not reopen
  // it or produce a second success (spec §4.1 "重复或迟到的终态").
  if (TERMINAL_EVENTS.has(type) && (state.status === 'interrupted' || state.status === 'error')) {
    return state;
  }

  switch (type) {
    case 'text_delta': {
      const turn = currentTurn(state);
      if (!turn) return state;
      return updateAssistant(state, {text: `${turn.assistant.text}${event.text || ''}`});
    }
    case 'thinking_delta': {
      const turn = currentTurn(state);
      if (!turn) return state;
      return updateAssistant(state, {thinking: `${turn.assistant.thinking}${event.text || ''}`});
    }
    case 'tool_use_start': {
      const id = event.id || event.tool_use_id;
      if (!id) return state;
      return updateTools(state, (tools) => {
        if (tools.some((tool) => tool.id === id)) return tools;
        return [...tools, {id, name: event.name || 'tool', status: 'running', input: '', output: null}];
      });
    }
    case 'tool_input_delta': {
      const id = event.id || event.tool_use_id;
      if (!id) return state;
      return updateTools(state, (tools) =>
        tools.map((tool) =>
          tool.id === id ? {...tool, input: `${tool.input}${event.partial_json || ''}`} : tool,
        ),
      );
    }
    case 'tool_result': {
      const id = event.tool_use_id || event.id;
      if (!id) return state;
      let duplicate = false;
      const next = updateTools(state, (tools) => {
        const existing = tools.find((tool) => tool.id === id);
        if (existing && existing.status === 'done') {
          duplicate = true;
          return tools;
        }
        const merged = {
          ...(existing || {id, name: event.name || 'tool', input: ''}),
          status: 'done',
          output: event.output ?? existing?.output ?? null,
        };
        const without = tools.filter((tool) => tool.id !== id);
        return [...without, addBoardItemIfAny(merged)];
      });
      return duplicate ? state : next;
    }
    case 'user_choice_requested': {
      const pendingChoice = {
        toolUseId: event.tool_use_id || '',
        question: event.question || '需要补充条件',
        options: Array.isArray(event.options) ? event.options : [],
      };
      return updateTurn(
        {...state, status: 'paused', pendingChoice},
        {status: 'paused'},
      );
    }
    case 'done': {
      const status = state.pendingChoice ? 'paused' : 'idle';
      return updateTurn({...state, status, pendingChoice: state.pendingChoice}, {
        status: status === 'paused' ? 'paused' : 'done',
      });
    }
    case 'error': {
      const message = String(event.message || '分析失败，请重试');
      return updateTurn({...state, status: 'error', error: message}, {status: 'error'});
    }
    case 'session_superseded':
    case 'stream_interrupted': {
      return updateTurn({...state, status: 'interrupted'}, {status: 'interrupted'});
    }
    default:
      return state;
  }
}

/** Stop the running turn: partial text and results stay on screen. */
export function stopTurn(state) {
  if (state.status !== 'streaming') return state;
  return updateTurn({...state, status: 'interrupted'}, {status: 'interrupted'});
}
