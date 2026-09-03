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

// --- Cross-modal async identity (AC-C1..C6) -----------------------------
// requestEpoch and renderToken must stay monotonic across modal
// open/close cycles; reopening from a fresh state would reuse the same
// small integers and let entity A's late async work corrupt entity B.

test("reopen keeps request and render counters monotonic", () => {
  let closedA = createOntologyGraphViewState();
  // open A, run one request and one render, then close A.
  closedA = openOntologyGraphView(closedA, { code: "A" });
  closedA = beginOntologyGraphRequest(closedA);
  closedA = beginOntologyGraphRender(closedA);
  const epochAfterCloseA = closedA.requestEpoch;
  const tokenAfterCloseA = closedA.renderToken;
  closedA = closeOntologyGraphView(closedA);
  // open B from A's closed state (runtime keeps a single state object).
  const openedB = openOntologyGraphView(closedA, { code: "B" });
  assert.ok(openedB.requestEpoch > epochAfterCloseA, "B requestEpoch must exceed A's closed value");
  assert.ok(openedB.renderToken > tokenAfterCloseA, "B renderToken must exceed A's closed value");
});

test("request epochs never collide across reopen", () => {
  let closedA = createOntologyGraphViewState();
  closedA = openOntologyGraphView(closedA, { code: "A" });
  closedA = beginOntologyGraphRequest(closedA);
  const epochA = closedA.requestEpoch;
  closedA = closeOntologyGraphView(closedA);
  let openedB = openOntologyGraphView(closedA, { code: "B" });
  openedB = beginOntologyGraphRequest(openedB);
  const epochB = openedB.requestEpoch;
  assert.notEqual(epochA, epochB, "A and B request epochs must differ");
  assert.ok(epochB > epochA, "B request epoch must be strictly larger");
  let afterStaleFinish = finishOntologyGraphRequest(openedB, epochA);
  assert.equal(afterStaleFinish.requestBusy, true, "A's finish must not clear B's busy");
  const afterCurrentFinish = finishOntologyGraphRequest(afterStaleFinish, epochB);
  assert.equal(afterCurrentFinish.requestBusy, false, "B's own finish clears B's busy");
});

test("render tokens never collide across reopen", () => {
  let closedA = createOntologyGraphViewState();
  closedA = openOntologyGraphView(closedA, { code: "A" });
  closedA = beginOntologyGraphRender(closedA);
  const tokenA = closedA.renderToken;
  closedA = closeOntologyGraphView(closedA);
  let openedB = openOntologyGraphView(closedA, { code: "B" });
  openedB = beginOntologyGraphRender(openedB);
  const tokenB = openedB.renderToken;
  assert.notEqual(tokenA, tokenB, "A and B render tokens must differ");
  assert.ok(tokenB > tokenA, "B render token must be strictly larger");
  assert.equal(isOntologyGraphRenderCurrent(openedB, tokenA), false, "A's token must not be current in B");
  let afterStaleFinish = finishOntologyGraphRender(openedB, tokenA);
  assert.equal(afterStaleFinish.renderBusy, true, "A's render finish must not clear B's busy");
  const afterCurrentFinish = finishOntologyGraphRender(afterStaleFinish, tokenB);
  assert.equal(afterCurrentFinish.renderBusy, false, "B's own render finish clears B's busy");
});

test("reopen resets business state but keeps async identity growing", () => {
  let closedA = createOntologyGraphViewState();
  closedA = openOntologyGraphView(closedA, { code: "A", name: "Entity A" });
  closedA = receiveOntologyGraphData(closedA, STRATEGY_EXPAND, { nodes: [{ id: "a" }], links: [] });
  closedA = selectOntologyGraphLayout(closedA, LAYOUT_RADIAL);
  closedA = beginOntologyGraphRequest(closedA);
  closedA = beginOntologyGraphRender(closedA);
  const epochAfterCloseA = closedA.requestEpoch;
  const tokenAfterCloseA = closedA.renderToken;
  closedA = closeOntologyGraphView(closedA);
  const entityB = { code: "B", name: "Entity B" };
  const openedB = openOntologyGraphView(closedA, entityB);
  assert.equal(openedB.open, true);
  assert.deepEqual(openedB.entity, entityB, "B must carry its own entity copy");
  assert.equal(openedB.layout, LAYOUT_CLUSTER, "reopen defaults to cluster layout");
  assert.equal(openedB.strategy, STRATEGY_CONTEXT, "reopen defaults to context strategy");
  assert.equal(openedB.data, null, "reopen must clear the previous graph data");
  assert.equal(openedB.requestBusy, false, "reopen must clear request busy");
  assert.equal(openedB.renderBusy, false, "reopen must clear render busy");
  assert.ok(openedB.requestEpoch > epochAfterCloseA, "requestEpoch keeps growing across reopen");
  assert.ok(openedB.renderToken > tokenAfterCloseA, "renderToken keeps growing across reopen");
});

test("twenty reopen cycles produce strictly increasing unique epochs and tokens", () => {
  const epochs = [];
  const tokens = [];
  let state = createOntologyGraphViewState();
  for (let round = 0; round < 20; round += 1) {
    state = openOntologyGraphView(state, { code: `E${round}` });
    state = beginOntologyGraphRequest(state);
    epochs.push(state.requestEpoch);
    state = beginOntologyGraphRender(state);
    tokens.push(state.renderToken);
    state = closeOntologyGraphView(state);
  }
  assert.equal(epochs.length, 20);
  assert.equal(tokens.length, 20);
  for (let index = 1; index < epochs.length; index += 1) {
    assert.ok(epochs[index] > epochs[index - 1], `epoch must strictly increase at ${index}`);
    assert.ok(tokens[index] > tokens[index - 1], `token must strictly increase at ${index}`);
  }
  assert.equal(new Set(epochs).size, epochs.length, "epochs must not repeat");
  assert.equal(new Set(tokens).size, tokens.length, "tokens must not repeat");
});
