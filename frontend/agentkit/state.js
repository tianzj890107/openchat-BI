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

import {turnsBoardItems} from './results.js';

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


/**
 * Build the entry URL a host (V6.1 risk card, another cockpit) links to.
 * One helper keeps hosts from hand-assembling the handoff contract.
 */
export function buildHandoffUrl(card = {}, basePath = "") {
  const base = String(basePath || "").replace(/\/+$/, "");
  const params = new URLSearchParams();
  const put = (key, value) => {
    const text = String(value ?? "").trim();
    if (text) params.set(key, text);
  };
  put("source", card.source);
  put("anchor", card.anchor || card.risk);
  put("period", card.period);
  const filters = card.filters || {};
  const filterPairs = Object.entries(filters)
    .map(([key, value]) => `${key}=${value}`)
    .filter((pair) => pair.length > 1);
  if (filterPairs.length) params.set("filters", filterPairs.join(";"));
  if (Array.isArray(card.evidence) && card.evidence.length) {
    params.set("evidence", card.evidence.join(","));
  }
  put("handoff", card.handoffId || card.handoff);
  const query = params.toString();
  return `${base}/workbench-agentkit${query ? `?${query}` : ""}`;
}


/**
 * Rebuild display turns from a stored conversation record (history restore).
 * A second assistant message in the same stored turn is appended to the same
 * assistant bubble. Tool results from user-role messages attach by call ID.
 */
export function hydrateTurns(messages) {
  const turns = [];
  for (const message of messages || []) {
    const blocks = Array.isArray(message?.content)
      ? message.content
      : [{type: 'text', text: String(message?.content ?? '')}];
    const text = blocks
      .filter((block) => block && block.type === 'text')
      .map((block) => block.text || '')
      .join('\n')
      .trim();
    const tools = blocks
      .filter((block) => block && block.type === 'tool_use')
      .map((block) => ({
        id: block.id || block.tool_use_id || `history-tool-${turns.length}`,
        name: block.name || 'tool',
        status: 'done',
        input: JSON.stringify(block.input ?? {}),
        output: null,
      }));
    const last = turns[turns.length - 1];
    if (message?.role === 'assistant') {
      if (last) {
        last.assistant = {
          text: [last.assistant.text, text].filter(Boolean).join('\n'),
          thinking: '',
          tools: [...last.assistant.tools, ...tools],
        };
      }
    } else {
      for (const block of blocks) {
        if (block?.type !== 'tool_result') continue;
        const tool = last?.assistant.tools.find((item) => item.id === block.tool_use_id);
        if (tool) {
          tool.output = Array.isArray(block.content)
            ? block.content.filter((part) => part?.type === 'text').map((part) => part.text).join('\n')
            : block.content ?? null;
          if (block.is_error) tool.errorCode = 'TOOL_FAILED';
        }
      }
      if (text) {
        turns.push({
          id: `history-${turns.length}`,
          user: text,
          status: 'done',
          assistant: {text: '', thinking: '', tools},
        });
      }
    }
  }
  return turns;
}


/** Only a usable card handoff is sent as request scope. */
export function scopeFromHandoff(handoff) {
  if (!handoff?.active || handoff.invalid) return null;
  const scope = {
    source: handoff.source || "",
    anchor: handoff.anchor,
    period: handoff.period,
    filters: handoff.filters || {},
    evidence: handoff.evidence || [],
  };
  if (handoff.handoffId) scope.handoff_id = handoff.handoffId;
  return scope;
}

/**
 * One session per handoff card, kept for the tab's lifetime so a refresh
 * resumes the established analysis session instead of starting a new one.
 */
export function handoffSessionStorageKey(handoff) {
  return handoff?.handoffId ? `agentkit.handoff-session.${handoff.handoffId}` : "";
}

/** The conversation a handoff card already produced, so a refresh can reopen it. */
export function handoffConversationStorageKey(handoff) {
  return handoff?.handoffId ? `agentkit.handoff-conversation.${handoff.handoffId}` : "";
}

export function resolveHandoffSession(handoff, storage = null) {
  const key = handoffSessionStorageKey(handoff);
  if (!key) return "";
  try {
    const existing = storage?.getItem?.(key);
    if (existing) return existing;
    const created = `agentkit-${handoff.handoffId}-${Math.random().toString(16).slice(2)}`;
    storage?.setItem?.(key, created);
    return created;
  } catch (_) {
    return "";
  }
}

/**
 * Resume a paused turn for /api/choice: the backend allocates a NEW request
 * turn_id for the continuation, so the previous id must be released before the
 * resumed stream is accepted.
 */
export function resumeTurn(state) {
  if (state.status !== 'paused') return state;
  return {
    ...state,
    status: 'streaming',
    activeTurnId: null,
    pendingChoice: null,
    error: '',
  };
}


/**
 * Persistable snapshot of a conversation: the turns already carry the text,
 * tool runs, boards, evidence and ontology hits, so one round trip restores
 * the whole right pane.
 */
export function snapshotFromState(state) {
  const turns = (state?.turns || []).map((turn) => JSON.parse(JSON.stringify(turn)));
  return {version: 1, turns};
}

/** Validate a stored snapshot; malformed history falls back to messages. */
export function turnsFromSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.turns)) return null;
  const usable = snapshot.turns.filter((turn) => turn && typeof turn === 'object' && turn.user);
  if (!usable.length) return null;
  return usable.map((turn, index) => ({
    id: String(turn.id || `restored-${index}`),
    user: String(turn.user || ''),
    status: 'done',
    assistant: {
      text: String(turn.assistant?.text || ''),
      thinking: String(turn.assistant?.thinking || ''),
      tools: Array.isArray(turn.assistant?.tools)
        ? turn.assistant.tools.filter((tool) => tool && tool.id)
        : [],
    },
  }));
}

/**
 * Turn ids must stay unique across restored history and new turns: a repeated
 * `turn-1` breaks React keys and assistant-ui message ids (duplicate ids made
 * the page blank after a follow-up on a restored conversation).
 */
export function nextTurnId(turns) {
  let max = 0;
  for (const turn of turns || []) {
    const match = /^turn-(\d+)$/.exec(String(turn?.id || ''));
    if (match) max = Math.max(max, Number(match[1]));
  }
  return `turn-${max + 1}`;
}

/** Begin a turn: user text lands immediately, the assistant bubble streams in. */
export function startTurn(state, {text, sessionId} = {}) {
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
        id: nextTurnId(state.turns),
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

/** Right-pane results: every table/chart a turn produced, with stable ids. */
export function boardItems(state) {
  return turnsBoardItems(state.turns || []);
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
    // The backend emits `tool_start` / `tool_input`; the older `tool_use_*`
    // spellings stay accepted so a stream from an earlier build still folds.
    case 'tool_start':
    case 'tool_use_start': {
      const id = event.id || event.tool_use_id;
      if (!id) return state;
      return updateTools(state, (tools) => {
        if (tools.some((tool) => tool.id === id)) return tools;
        return [...tools, {id, name: event.name || 'tool', status: 'running', input: '', output: null}];
      });
    }
    case 'tool_input':
    case 'tool_input_delta': {
      const id = event.id || event.tool_use_id;
      if (!id) return state;
      const incoming = event.input ?? event.partial_json ?? '';
      return updateTools(state, (tools) => {
        if (!tools.some((tool) => tool.id === id)) {
          return [...tools, {id, name: event.name || 'tool', status: 'running', input: incoming, output: null}];
        }
        return tools.map((tool) => (tool.id === id ? {...tool, input: incoming} : tool));
      });
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
          input: event.input ?? existing?.input ?? '',
          output: event.output ?? existing?.output ?? null,
          entities: Array.isArray(event.ontology_entities) ? event.ontology_entities : existing?.entities ?? [],
          table: event.table ?? existing?.table ?? null,
          chart: event.chart ?? existing?.chart ?? null,
          multiChart: event.multi_chart ?? existing?.multiChart ?? null,
          durationMs: event.duration_ms ?? existing?.durationMs,
          executionStatus: event.execution_status || existing?.executionStatus || '',
          attempt: event.attempt ?? existing?.attempt,
          errorCode: event.error_code || existing?.errorCode || '',
        };
        // A result can arrive without a preceding tool_start: append it once.
        return existing ? tools.map((tool) => tool.id === id ? merged : tool) : [...tools, merged];
      });
      return duplicate ? state : next;
    }
    case 'scope_accepted': {
      // The analysis service echoed the range it accepted; show it as
      // confirmed instead of trusting the browser-only banner.
      return {...state, scopeConfirmed: event.scope || null};
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
