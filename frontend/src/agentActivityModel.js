/**
 * Analytics SSE -> Pro UI-style activity state.
 *
 * This module deliberately contains no DOM, React or network code. The
 * workbench runtime remains the owner of requests, history and rendered
 * artifacts; this reducer only gives the conversation layer a stable view of
 * what the current turn is doing.
 */

export const ACTIVITY_STATUS = Object.freeze({
  RUNNING: "running",
  COMPLETE: "complete",
  ERROR: "error",
  CANCELLED: "cancelled",
});

export const AGENT_STATUS = Object.freeze({
  IDLE: "idle",
  RUNNING: "running",
  AWAITING_CHOICE: "awaiting_choice",
  COMPLETED: "completed",
  INTERRUPTED: "interrupted",
  FAILED: "failed",
  SUPERSEDED: "superseded",
});

const TERMINAL_AGENT_STATUSES = new Set([
  AGENT_STATUS.COMPLETED,
  AGENT_STATUS.INTERRUPTED,
  AGENT_STATUS.FAILED,
  AGENT_STATUS.SUPERSEDED,
]);

const FAILED_AGENT_STATUSES = new Set([
  AGENT_STATUS.INTERRUPTED,
  AGENT_STATUS.FAILED,
  AGENT_STATUS.SUPERSEDED,
]);

function now(value) {
  return Number.isFinite(value) ? Number(value) : Date.now();
}

function activityText(value) {
  const text = String(value == null ? "" : value);
  return text.length > 180 ? `${text.slice(0, 179)}…` : text;
}

function isTerminal(status) {
  return TERMINAL_AGENT_STATUSES.has(status);
}

function isFailedTerminal(status) {
  return FAILED_AGENT_STATUSES.has(status);
}

function withActivity(state, activity) {
  const activities = state.activities.slice();
  const index = activities.findIndex((item) => item.id === activity.id);
  if (index >= 0) activities[index] = activity;
  else activities.push(activity);
  return { ...state, activities };
}

function activityById(state, id) {
  return state.activities.find((item) => item.id === id) || null;
}

function upsertActivity(state, {
  id,
  kind = "tool",
  name = "",
  status = ACTIVITY_STATUS.RUNNING,
  input,
  output,
  text,
  textDelta,
  durationMs,
  chart,
  table,
  multiChart,
  ontologyEntities,
  at,
}) {
  if (!id) return { state, activity: null };
  const previous = activityById(state, id);
  const timestamp = now(at);
  const nextText = textDelta !== undefined
    ? `${previous?.text || ""}${String(textDelta || "")}`
    : (text !== undefined ? String(text || "") : previous?.text || "");
  const terminal = status !== ACTIVITY_STATUS.RUNNING;
  const activity = {
    id: String(id),
    kind: kind || previous?.kind || "tool",
    name: name || previous?.name || "工具调用",
    status,
    input: input !== undefined ? input : previous?.input,
    output: output !== undefined ? output : previous?.output,
    text: nextText,
    durationMs: durationMs !== undefined
      ? Number(durationMs) || 0
      : (previous?.durationMs ?? null),
    chart: chart !== undefined ? chart : (previous?.chart ?? null),
    table: table !== undefined ? table : (previous?.table ?? null),
    multiChart: multiChart !== undefined ? multiChart : (previous?.multiChart ?? null),
    ontologyEntities: ontologyEntities !== undefined
      ? ontologyEntities
      : (previous?.ontologyEntities ?? []),
    startedAt: previous?.startedAt || timestamp,
    completedAt: terminal ? timestamp : (previous?.completedAt || null),
  };
  return { state: withActivity(state, activity), activity };
}

function finishActivities(state, status, at) {
  const timestamp = now(at);
  return state.activities.map((item) => {
    if (item.status !== ACTIVITY_STATUS.RUNNING) return item;
    return {
      ...item,
      status,
      completedAt: timestamp,
    };
  });
}

function terminalState(state, status, { at, message = "" } = {}) {
  if (isTerminal(state.status)) return state;
  if (state.status === AGENT_STATUS.AWAITING_CHOICE && status === AGENT_STATUS.COMPLETED) {
    return state;
  }
  const activityStatus = status === AGENT_STATUS.FAILED
    ? ACTIVITY_STATUS.ERROR
    : ACTIVITY_STATUS.CANCELLED;
  return {
    ...state,
    status,
    busy: false,
    error: message || state.error,
    activities: finishActivities(state, activityStatus, at),
    updatedAt: now(at),
  };
}

function eventTurnId(event) {
  return event?.turn_id == null ? "" : String(event.turn_id);
}

export function createAgentActivityState() {
  return {
    turnId: null,
    status: AGENT_STATUS.IDLE,
    busy: false,
    text: "",
    userText: "",
    activities: [],
    choices: [],
    activeChoice: null,
    sop: null,
    iteration: null,
    error: "",
    lastEventType: "",
    startedAt: null,
    updatedAt: null,
  };
}

export function beginAgentTurn(state, { text = "", at } = {}) {
  const timestamp = now(at);
  return {
    ...createAgentActivityState(),
    status: AGENT_STATUS.RUNNING,
    busy: true,
    userText: String(text || ""),
    startedAt: timestamp,
    updatedAt: timestamp,
    lastEventType: "user_message",
  };
}

export function resetAgentActivity(state, { at } = {}) {
  const timestamp = now(at);
  return {
    ...createAgentActivityState(),
    startedAt: state?.startedAt || null,
    updatedAt: timestamp,
  };
}

export function stopAgentTurn(state, at) {
  if (!state || state.status === AGENT_STATUS.IDLE || isTerminal(state.status)) return state;
  return {
    ...terminalState(state, AGENT_STATUS.INTERRUPTED, {
      at,
      message: "已停止生成",
    }),
    stoppedByUser: true,
  };
}

/**
 * Apply one Analytics event. The returned `activity` is the single activity
 * touched by this event, which lets callers update one existing tool row
 * without re-rendering the whole transcript.
 */
export function applyAgentEvent(state, event, { at } = {}) {
  if (!event || typeof event.type !== "string") return { state, activity: null, ignored: true };
  if (!state || typeof state !== "object") state = createAgentActivityState();
  const timestamp = now(at);
  const eventTurn = eventTurnId(event);

  if (eventTurn && state.turnId && eventTurn !== state.turnId) {
    return { state, activity: null, ignored: true };
  }
  if (eventTurn && !state.turnId) state = { ...state, turnId: eventTurn };

  // A tool call is identified by its backend id. Once it has produced a
  // result, a delayed start/input frame for the same id must not reopen the
  // completed row. Token ordering is normally guaranteed by the SSE stream,
  // but reconnects and buffered frames can otherwise create a duplicate
  // "running" state after the result is already visible.
  if (event.type === "tool_start" || event.type === "tool_input") {
    const previous = event.id == null ? null : activityById(state, String(event.id));
    if (previous && previous.status !== ACTIVITY_STATUS.RUNNING) {
      return { state, activity: previous, ignored: true };
    }
  }

  // A late frame after a terminal state must never mutate the visible turn.
  // Repeating the same terminal event is a no-op rather than a new state.
  if (isTerminal(state.status)) {
    return { state, activity: null, ignored: true };
  }

  state = { ...state, lastEventType: event.type, updatedAt: timestamp };
  switch (event.type) {
    case "user_message":
      return {
        state: {
          ...state,
          userText: String(event.text || ""),
          status: AGENT_STATUS.RUNNING,
          busy: true,
        },
        activity: null,
        ignored: false,
      };

    case "iteration_start":
      return {
        state: { ...state, iteration: Number(event.iteration) || state.iteration },
        activity: null,
        ignored: false,
      };

    case "text_delta": {
      if (isTerminal(state.status)) return { state, activity: null, ignored: true };
      return {
        state: {
          ...state,
          status: AGENT_STATUS.RUNNING,
          busy: true,
          text: `${state.text || ""}${String(event.text || "")}`,
        },
        activity: null,
        ignored: false,
      };
    }

    case "thinking_delta": {
      if (isTerminal(state.status)) return { state, activity: null, ignored: true };
      const reasoning = state.activities.find((item) => item.kind === "reasoning");
      const result = upsertActivity(state, {
        id: reasoning?.id || `reasoning:${state.turnId || "current"}`,
        kind: "reasoning",
        name: "思考摘要",
        status: ACTIVITY_STATUS.RUNNING,
        textDelta: event.text,
        at: timestamp,
      });
      return {
        state: { ...result.state, status: AGENT_STATUS.RUNNING, busy: true },
        activity: result.activity,
        ignored: false,
      };
    }

    case "tool_start":
    case "tool_input":
    case "tool_result": {
      if (isTerminal(state.status)) return { state, activity: null, ignored: true };
      const isResult = event.type === "tool_result";
      const result = upsertActivity(state, {
        id: event.id,
        kind: "tool",
        name: event.name,
        status: isResult ? ACTIVITY_STATUS.COMPLETE : ACTIVITY_STATUS.RUNNING,
        input: isResult ? event.input : (event.input !== undefined ? event.input : undefined),
        output: isResult ? event.output : undefined,
        durationMs: isResult ? event.duration_ms : undefined,
        chart: isResult ? (event.chart || null) : undefined,
        table: isResult ? (event.table || null) : undefined,
        multiChart: isResult ? (event.multi_chart || null) : undefined,
        ontologyEntities: isResult ? (event.ontology_entities || []) : undefined,
        at: timestamp,
      });
      return {
        state: { ...result.state, status: AGENT_STATUS.RUNNING, busy: true },
        activity: result.activity,
        ignored: false,
      };
    }

    case "sop_progress":
      return {
        state: {
          ...state,
          status: AGENT_STATUS.RUNNING,
          busy: true,
          sop: {
            step: Number(event.step) || state.sop?.step || 0,
            detail: String(event.detail || ""),
          },
        },
        activity: null,
        ignored: false,
      };

    case "llm_response": {
      const reasoning = state.activities.find(
        (item) => item.kind === "reasoning" && item.status === ACTIVITY_STATUS.RUNNING,
      );
      if (!reasoning) return { state: { ...state, status: AGENT_STATUS.RUNNING }, activity: null, ignored: false };
      const result = upsertActivity(state, {
        id: reasoning.id,
        kind: "reasoning",
        name: reasoning.name,
        status: ACTIVITY_STATUS.COMPLETE,
        at: timestamp,
      });
      return { state: result.state, activity: result.activity, ignored: false };
    }

    case "user_choice_requested": {
      const id = String(event.tool_use_id || `choice:${state.choices.length + 1}`);
      const choice = {
        id,
        question: String(event.question || ""),
        options: Array.isArray(event.options) ? event.options : [],
        resolved: false,
        labels: [],
      };
      const existing = state.choices.findIndex((item) => item.id === id);
      const choices = state.choices.slice();
      if (existing >= 0) choices[existing] = choice;
      else choices.push(choice);
      return {
        state: {
          ...state,
          choices,
          activeChoice: id,
          status: AGENT_STATUS.AWAITING_CHOICE,
          busy: false,
        },
        activity: null,
        ignored: false,
      };
    }

    case "awaiting_user_choice":
      return {
        state: {
          ...state,
          status: AGENT_STATUS.AWAITING_CHOICE,
          busy: false,
        },
        activity: null,
        ignored: false,
      };

    case "user_choice_resolved": {
      const id = String(event.tool_use_id || state.activeChoice || "");
      const labels = Array.isArray(event.choice_labels)
        ? event.choice_labels
        : (event.choice_label ? [event.choice_label] : []);
      const choices = state.choices.map((choice) => (
        choice.id === id
          ? { ...choice, resolved: true, labels }
          : choice
      ));
      return {
        state: {
          ...state,
          choices,
          activeChoice: null,
          status: AGENT_STATUS.RUNNING,
          busy: true,
        },
        activity: null,
        ignored: false,
      };
    }

    case "done":
      return {
        state: terminalState(state, AGENT_STATUS.COMPLETED, { at: timestamp }),
        activity: null,
        ignored: false,
      };

    case "error":
      return {
        state: terminalState(state, AGENT_STATUS.FAILED, {
          at: timestamp,
          message: String(event.message || "unknown"),
        }),
        activity: null,
        ignored: false,
      };

    case "session_superseded":
      return {
        state: terminalState(state, AGENT_STATUS.SUPERSEDED, { at: timestamp }),
        activity: null,
        ignored: false,
      };

    case "stream_interrupted":
      return {
        state: terminalState(state, AGENT_STATUS.INTERRUPTED, {
          at: timestamp,
          message: String(event.message || "生成中断，内容可能不完整"),
        }),
        activity: null,
        ignored: false,
      };

    default:
      return { state, activity: null, ignored: false };
  }
}

export function getPrimaryActivity(state) {
  if (!state?.activities?.length) return null;
  const runningTools = state.activities.filter(
    (item) => item.kind === "tool" && item.status === ACTIVITY_STATUS.RUNNING,
  );
  if (runningTools.length) return runningTools[runningTools.length - 1];
  const running = state.activities.filter((item) => item.status === ACTIVITY_STATUS.RUNNING);
  if (running.length) return running[running.length - 1];
  const completedTools = state.activities.filter((item) => item.kind === "tool");
  return completedTools[completedTools.length - 1] || state.activities[state.activities.length - 1];
}

export function getStatusLabel(state) {
  if (!state || state.status === AGENT_STATUS.IDLE || !state.status) return "待开始";
  if (state.status === AGENT_STATUS.AWAITING_CHOICE) return "等待选择";
  if (state.status === AGENT_STATUS.COMPLETED) return "分析完成";
  if (state.status === AGENT_STATUS.INTERRUPTED) {
    return state.stoppedByUser ? "已停止" : "生成中断";
  }
  if (state.status === AGENT_STATUS.FAILED) return "分析失败";
  if (state.status === AGENT_STATUS.SUPERSEDED) return "会话已重建";
  const primary = getPrimaryActivity(state);
  if (primary?.status === ACTIVITY_STATUS.RUNNING && primary.kind === "tool") {
    return "正在执行工具";
  }
  return "正在分析";
}

export function getStatusDetail(state) {
  if (!state) return "";
  if (state.status === AGENT_STATUS.AWAITING_CHOICE) {
    const active = state.choices.find((item) => item.id === state.activeChoice);
    return active?.question ? activityText(active.question) : "需要您确认分析口径";
  }
  if (state.status === AGENT_STATUS.COMPLETED) return "已整理分析结果";
  if (state.status === AGENT_STATUS.INTERRUPTED) {
    return state.stoppedByUser
      ? "已保留当前已生成内容，未保存为完成回答"
      : "连接中断，内容可能不完整";
  }
  if (state.status === AGENT_STATUS.FAILED) return activityText(state.error || "本轮分析失败");
  if (state.status === AGENT_STATUS.SUPERSEDED) return "上一轮生成已被会话重建中断";
  if (state.status === AGENT_STATUS.RUNNING) {
    const primary = getPrimaryActivity(state);
    if (primary?.kind === "tool" && primary.status === ACTIVITY_STATUS.RUNNING) {
      return activityText(primary.name || "工具调用");
    }
    if (primary?.kind === "reasoning" && primary.status === ACTIVITY_STATUS.RUNNING) {
      return "模型正在整理分析思路";
    }
    if (primary?.kind === "tool") return "已整理分析结果";
    return "正在理解问题并组织分析";
  }
  return "";
}
