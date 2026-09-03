import test from "node:test";
import assert from "node:assert/strict";
import {
  LAYOUT_CLUSTER,
  LAYOUT_RADIAL,
  STRATEGY_CONTEXT,
  STRATEGY_EXPAND,
  beginOntologyGraphRender,
  beginOntologyGraphRequest,
  closeOntologyGraphView,
  createOntologyGraphViewState,
  finishOntologyGraphRender,
  finishOntologyGraphRequest,
  isOntologyGraphBusy,
  isOntologyGraphRenderCurrent,
  openOntologyGraphView,
  receiveOntologyGraphData,
  selectOntologyGraphLayout,
} from "../src/ontologyGraphViewState.js";

test("new view state defaults to cluster layout with context strategy and closed modal", () => {
  const state = createOntologyGraphViewState();
  assert.equal(state.layout, LAYOUT_CLUSTER);
  assert.equal(state.strategy, STRATEGY_CONTEXT);
  assert.equal(state.open, false);
  assert.equal(state.data, null);
  assert.equal(state.renderToken, 0);
});

test("layout change reuses existing graph data and never triggers a fetch", () => {
  const entity = { code: "BO1" };
  const graph = { nodes: [{ id: "a" }], links: [] };
  let state = openOntologyGraphView(createOntologyGraphViewState(), entity);
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, graph);
  let fetchCalls = 0;
  const previousFetch = globalThis.fetch;
  globalThis.fetch = () => { fetchCalls += 1; return Promise.resolve({}); };
  try {
    state = selectOntologyGraphLayout(state, LAYOUT_RADIAL);
  } finally {
    globalThis.fetch = previousFetch;
  }
  assert.equal(fetchCalls, 0);
  assert.equal(state.layout, LAYOUT_RADIAL);
  assert.equal(state.data, graph, "existing graph data must be reused, not cleared");
  assert.equal(state.strategy, STRATEGY_CONTEXT);
});

test("strategy response replaces graph data while keeping current layout preference", () => {
  const entity = { code: "BO1" };
  const contextGraph = { nodes: [{ id: "a" }], links: [] };
  const expandGraph = { nodes: [{ id: "a" }, { id: "b" }], links: [{ source: "a", target: "b" }] };
  let state = openOntologyGraphView(createOntologyGraphViewState(), entity);
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, contextGraph);
  state = selectOntologyGraphLayout(state, LAYOUT_RADIAL);
  state = receiveOntologyGraphData(state, STRATEGY_EXPAND, expandGraph);
  assert.equal(state.layout, LAYOUT_RADIAL);
  assert.equal(state.strategy, STRATEGY_EXPAND);
  assert.equal(state.data, expandGraph);
  assert.notEqual(state.data, contextGraph);
});

test("stale render tokens can never overwrite newer state", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  const tokenAtOpen = state.renderToken;
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, { nodes: [{ id: "a" }], links: [] });
  const tokenAfterData = state.renderToken;
  assert.ok(isOntologyGraphRenderCurrent(state, tokenAfterData));
  assert.ok(!isOntologyGraphRenderCurrent(state, tokenAtOpen));
  state = selectOntologyGraphLayout(state, LAYOUT_RADIAL);
  assert.ok(!isOntologyGraphRenderCurrent(state, tokenAfterData), "old token must lose currency after layout switch");
  assert.ok(isOntologyGraphRenderCurrent(state, state.renderToken));
});

test("closing the modal invalidates in-flight ECharts mounts", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, { nodes: [{ id: "a" }], links: [] });
  const tokenBeforeClose = state.renderToken;
  state = closeOntologyGraphView(state);
  assert.equal(state.open, false);
  assert.ok(!isOntologyGraphRenderCurrent(state, tokenBeforeClose));
  assert.ok(state.renderToken > tokenBeforeClose);
});

test("layout switch, strategy response and close all bump the render token", () => {
  const tokenLog = [];
  let state = openOntologyGraphView(createOntologyGraphViewState(), { code: "BO1" });
  tokenLog.push(state.renderToken);
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, { nodes: [{ id: "a" }], links: [] });
  tokenLog.push(state.renderToken);
  state = selectOntologyGraphLayout(state, LAYOUT_RADIAL);
  tokenLog.push(state.renderToken);
  state = receiveOntologyGraphData(state, STRATEGY_EXPAND, { nodes: [{ id: "a" }, { id: "b" }], links: [] });
  tokenLog.push(state.renderToken);
  state = closeOntologyGraphView(state);
  tokenLog.push(state.renderToken);
  for (let index = 1; index < tokenLog.length; index += 1) {
    assert.ok(tokenLog[index] > tokenLog[index - 1], `token must strictly increase at step ${index}`);
  }
});

test("begin request sets busy and bumps requestEpoch", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  const before = state.requestEpoch;
  state = beginOntologyGraphRequest(state);
  assert.equal(state.requestBusy, true);
  assert.equal(state.requestEpoch, before + 1);
  assert.equal(isOntologyGraphBusy(state), true);
});

test("request A then request B keeps only the newest busy lock", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state); // A
  const epochA = state.requestEpoch;
  state = beginOntologyGraphRequest(state); // B
  const epochB = state.requestEpoch;
  assert.ok(epochB > epochA);
  assert.equal(state.requestBusy, true);
  // A finish must not clear B busy.
  state = finishOntologyGraphRequest(state, epochA);
  assert.equal(state.requestBusy, true);
  assert.equal(state.requestEpoch, epochB);
});

test("finish request B clears busy only when B finishes", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state); // A
  const epochA = state.requestEpoch;
  state = beginOntologyGraphRequest(state); // B
  const epochB = state.requestEpoch;
  state = finishOntologyGraphRequest(state, epochA);
  assert.equal(state.requestBusy, true);
  state = finishOntologyGraphRequest(state, epochB);
  assert.equal(state.requestBusy, false);
  assert.equal(isOntologyGraphBusy(state), false);
});

test("stale epoch finish returns the state unchanged", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state);
  const epoch = state.requestEpoch;
  const before = JSON.stringify(state);
  const next = finishOntologyGraphRequest(state, 999);
  assert.equal(next, state);
  assert.equal(JSON.stringify(next), before);
});

test("begin render sets busy and bumps renderToken", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  const before = state.renderToken;
  state = beginOntologyGraphRender(state);
  assert.equal(state.renderBusy, true);
  assert.equal(state.renderToken, before + 1);
  assert.equal(isOntologyGraphBusy(state), true);
});

test("render A then render B keeps only the newest render lock", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRender(state); // A
  const tokenA = state.renderToken;
  state = beginOntologyGraphRender(state); // B
  const tokenB = state.renderToken;
  assert.ok(tokenB > tokenA);
  state = finishOntologyGraphRender(state, tokenA);
  assert.equal(state.renderBusy, true);
  assert.equal(state.renderToken, tokenB);
});

test("finish render B clears busy only when B finishes", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRender(state); // A
  const tokenA = state.renderToken;
  state = beginOntologyGraphRender(state); // B
  const tokenB = state.renderToken;
  state = finishOntologyGraphRender(state, tokenA);
  assert.equal(state.renderBusy, true);
  state = finishOntologyGraphRender(state, tokenB);
  assert.equal(state.renderBusy, false);
  assert.equal(isOntologyGraphBusy(state), false);
});

test("layout change invalidates old render token but keeps fetch busy", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state); // fetch still in flight
  const epoch = state.requestEpoch;
  const tokenBefore = state.renderToken;
  state = selectOntologyGraphLayout(state, LAYOUT_RADIAL);
  assert.ok(state.renderToken > tokenBefore, "layout switch must invalidate old renders");
  assert.ok(!isOntologyGraphRenderCurrent(state, tokenBefore));
  assert.equal(state.requestBusy, true, "fetch busy must survive layout switch");
  assert.equal(state.requestEpoch, epoch);
});

test("close clears busy and invalidates old epoch and render token", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state);
  const epochBefore = state.requestEpoch;
  state = beginOntologyGraphRender(state);
  const tokenBefore = state.renderToken;
  state = closeOntologyGraphView(state);
  assert.equal(state.open, false);
  assert.equal(state.requestBusy, false);
  assert.equal(state.renderBusy, false);
  assert.equal(isOntologyGraphBusy(state), false);
  assert.ok(state.requestEpoch > epochBefore);
  assert.ok(state.renderToken > tokenBefore);
  assert.ok(!isOntologyGraphRenderCurrent(state, tokenBefore));
});

test("finish of the current request and render clears busy after failure", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state);
  const epoch = state.requestEpoch;
  state = finishOntologyGraphRequest(state, epoch); // request failed
  assert.equal(state.requestBusy, false);
  state = beginOntologyGraphRender(state);
  const token = state.renderToken;
  state = finishOntologyGraphRender(state, token); // render failed / empty graph
  assert.equal(state.renderBusy, false);
  assert.equal(isOntologyGraphBusy(state), false);
});

test("empty or errored latest finish still releases the busy lock", () => {
  let state = createOntologyGraphViewState();
  state = openOntologyGraphView(state, { code: "BO1" });
  state = beginOntologyGraphRequest(state);
  const epoch = state.requestEpoch;
  state = receiveOntologyGraphData(state, STRATEGY_CONTEXT, { nodes: [], links: [] });
  state = finishOntologyGraphRequest(state, epoch);
  state = beginOntologyGraphRender(state);
  const token = state.renderToken;
  state = finishOntologyGraphRender(state, token);
  assert.equal(state.requestBusy, false);
  assert.equal(state.renderBusy, false);
  assert.equal(isOntologyGraphBusy(state), false);
});
