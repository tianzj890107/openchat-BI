import test from "node:test";
import assert from "node:assert/strict";
import {
  ACTIVITY_STATUS,
  AGENT_STATUS,
  applyAgentEvent,
  beginAgentTurn,
  createAgentActivityState,
  getPrimaryActivity,
  getStatusDetail,
  getStatusLabel,
  stopAgentTurn,
} from "../src/agentActivityModel.js";

const AT = 1_730_000_000_000;

function start(text = "分析本月收入") {
  return beginAgentTurn(createAgentActivityState(), { text, at: AT });
}

function apply(state, event, at = AT + 1) {
  return applyAgentEvent(state, event, { at }).state;
}

test("tool_start, tool_input and tool_result update one activity by id", () => {
  let state = start();
  state = apply(state, { type: "tool_start", id: "call-1", name: "MetricFactQuery" }, AT + 10);
  let primary = getPrimaryActivity(state);
  assert.equal(primary.id, "call-1");
  assert.equal(primary.status, ACTIVITY_STATUS.RUNNING);
  assert.equal(state.status, AGENT_STATUS.RUNNING);

  state = apply(state, {
    type: "tool_input",
    id: "call-1",
    name: "MetricFactQuery",
    input: { metric: "revenue" },
  }, AT + 20);
  primary = getPrimaryActivity(state);
  assert.deepEqual(primary.input, { metric: "revenue" });
  assert.equal(state.activities.filter((item) => item.id === "call-1").length, 1);

  state = apply(state, {
    type: "tool_result",
    id: "call-1",
    name: "MetricFactQuery",
    input: { metric: "revenue" },
    output: "ok",
    duration_ms: 42,
    chart: { id: "chart-1" },
  }, AT + 30);
  assert.equal(state.activities.filter((item) => item.id === "call-1").length, 1);
  assert.equal(state.activities[0].status, ACTIVITY_STATUS.COMPLETE);
  assert.equal(state.activities[0].durationMs, 42);
  assert.equal(state.activities[0].output, "ok");
  assert.deepEqual(state.activities[0].chart, { id: "chart-1" });
});

test("a result without a start event is still rendered once", () => {
  let state = start();
  state = apply(state, {
    type: "tool_result",
    id: "late-result",
    name: "TableGenerate",
    output: "done",
  });
  assert.equal(state.activities.length, 1);
  assert.equal(state.activities[0].status, ACTIVITY_STATUS.COMPLETE);
});

test("duplicate result and done frames stay idempotent", () => {
  let state = start();
  state = apply(state, { type: "tool_result", id: "call-1", name: "X", output: "one" });
  state = apply(state, { type: "tool_result", id: "call-1", name: "X", output: "two" });
  assert.equal(state.activities.length, 1);
  assert.equal(state.activities[0].output, "two");
  state = apply(state, { type: "done", turn_id: "turn-1" });
  const completed = state;
  state = apply(state, { type: "done", turn_id: "turn-1" });
  assert.equal(state, completed);
  assert.equal(getStatusLabel(state), "分析完成");
});

test("a late tool input cannot reopen a completed tool row", () => {
  let state = start();
  state = apply(state, { type: "tool_start", id: "call-1", name: "MetricFactQuery" });
  state = apply(state, { type: "tool_result", id: "call-1", name: "MetricFactQuery", output: "ok" });
  const completed = state;
  state = apply(state, { type: "tool_input", id: "call-1", name: "MetricFactQuery", input: { late: true } });
  assert.equal(state, completed);
  assert.equal(state.activities[0].status, ACTIVITY_STATUS.COMPLETE);
  assert.equal(state.activities[0].input, undefined);
});

test("reasoning is only created from explicit thinking_delta events", () => {
  let state = start();
  assert.equal(state.activities.filter((item) => item.kind === "reasoning").length, 0);
  state = apply(state, { type: "thinking_delta", text: "先核对口径，" });
  state = apply(state, { type: "thinking_delta", text: "再查询事实。" });
  const reasoning = state.activities.filter((item) => item.kind === "reasoning");
  assert.equal(reasoning.length, 1);
  assert.equal(reasoning[0].text, "先核对口径，再查询事实。");
  assert.equal(reasoning[0].status, ACTIVITY_STATUS.RUNNING);
});

test("an unresolved choice cannot be marked complete by a late done", () => {
  let state = start();
  state = apply(state, {
    type: "user_choice_requested",
    tool_use_id: "ask-1",
    question: "选择统计期间",
    options: [{ id: "m", label: "本月" }],
  });
  assert.equal(state.status, AGENT_STATUS.AWAITING_CHOICE);
  assert.equal(state.busy, false);
  assert.equal(getStatusLabel(state), "等待选择");
  state = apply(state, { type: "awaiting_user_choice", turn_id: "turn-1" });
  state = apply(state, { type: "done", turn_id: "turn-1" });
  assert.equal(state.status, AGENT_STATUS.AWAITING_CHOICE);
  assert.notEqual(getStatusLabel(state), "分析完成");

  state = apply(state, { type: "user_choice_resolved", tool_use_id: "ask-1", choice_labels: ["本月"] });
  assert.equal(state.status, AGENT_STATUS.RUNNING);
  assert.equal(state.activeChoice, null);
  state = apply(state, { type: "done", turn_id: "turn-1" });
  assert.equal(state.status, AGENT_STATUS.COMPLETED);
});

test("stale turn events and late text after a terminal state are ignored", () => {
  let state = start();
  state = apply(state, { type: "text_delta", turn_id: "turn-current", text: "当前" });
  const before = state;
  state = apply(state, { type: "text_delta", turn_id: "turn-old", text: "旧流" });
  assert.equal(state, before);
  assert.equal(state.text, "当前");

  state = apply(state, { type: "done", turn_id: "turn-current" });
  const completed = state;
  state = apply(state, { type: "text_delta", turn_id: "turn-current", text: "迟到" });
  assert.equal(state, completed);
  assert.equal(state.text, "当前");
});

test("stop preserves partial text and cancels the running tool", () => {
  let state = start();
  state = apply(state, { type: "text_delta", text: "已计算一半" });
  state = apply(state, { type: "tool_start", id: "call-1", name: "MetricFactQuery" });
  state = stopAgentTurn(state, AT + 100);
  assert.equal(state.status, AGENT_STATUS.INTERRUPTED);
  assert.equal(state.busy, false);
  assert.equal(state.text, "已计算一半");
  assert.equal(state.activities[0].status, ACTIVITY_STATUS.CANCELLED);
  assert.equal(getStatusLabel(state), "已停止");
  assert.equal(getStatusDetail(state), "已保留当前已生成内容，未保存为完成回答");
});

test("error and superseded states preserve partial content and never look successful", () => {
  let state = start();
  state = apply(state, { type: "text_delta", text: "部分结果" });
  state = apply(state, { type: "tool_start", id: "call-1", name: "MetricFactQuery" });
  const failed = apply(state, { type: "error", message: "upstream timeout" });
  assert.equal(failed.status, AGENT_STATUS.FAILED);
  assert.equal(failed.text, "部分结果");
  assert.equal(failed.activities[0].status, ACTIVITY_STATUS.ERROR);
  assert.equal(getStatusLabel(failed), "分析失败");

  const superseded = apply(state, { type: "session_superseded" });
  assert.equal(superseded.status, AGENT_STATUS.SUPERSEDED);
  assert.equal(superseded.text, "部分结果");
  assert.equal(getStatusLabel(superseded), "会话已重建");
});

test("network interruption is distinct from a user stop", () => {
  let state = start();
  state = apply(state, { type: "text_delta", text: "部分内容" });
  state = apply(state, { type: "stream_interrupted", message: "upstream disconnected" });
  assert.equal(state.status, AGENT_STATUS.INTERRUPTED);
  assert.equal(state.busy, false);
  assert.equal(state.text, "部分内容");
  assert.equal(state.stoppedByUser, undefined);
  assert.equal(getStatusLabel(state), "生成中断");
  assert.equal(getStatusDetail(state), "连接中断，内容可能不完整");
});

test("status detail identifies the running tool without exposing raw payloads", () => {
  let state = start();
  state = apply(state, { type: "tool_start", id: "call-1", name: "OntologyFactQuery" });
  assert.equal(getStatusLabel(state), "正在执行工具");
  assert.equal(getStatusDetail(state), "OntologyFactQuery");
  state = apply(state, { type: "tool_result", id: "call-1", name: "OntologyFactQuery", output: "ok" });
  assert.equal(getStatusLabel(state), "正在分析");
  assert.equal(getStatusDetail(state), "已整理分析结果");
});
