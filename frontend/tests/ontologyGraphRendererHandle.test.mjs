import test from "node:test";
import assert from "node:assert/strict";
import {
  createRadialGraphView,
  createSigmaGraphView,
  destroyGraphView,
} from "../src/ontologyGraphRendererHandle.js";

test("sigma view destroy calls kill exactly once across repeated destroys", () => {
  let kills = 0;
  const renderer = { kill: () => { kills += 1; }, relayout: () => {} };
  const view = createSigmaGraphView(renderer);
  view.destroy();
  view.destroy();
  view.destroy();
  assert.equal(kills, 1);
});

test("radial view destroy calls dispose exactly once across repeated destroys", () => {
  let disposes = 0;
  const chart = { dispose: () => { disposes += 1; } };
  const view = createRadialGraphView(chart, () => {});
  view.destroy();
  view.destroy();
  assert.equal(disposes, 1);
});

test("repeated destroy on the same view is idempotent", () => {
  let kills = 0;
  const renderer = { kill: () => { kills += 1; }, relayout: () => {} };
  const view = createSigmaGraphView(renderer);
  destroyGraphView(view);
  destroyGraphView(view);
  destroyGraphView(view);
  assert.equal(kills, 1);
});

test("destroyGraphView(null) and undefined are safe no-ops", () => {
  assert.doesNotThrow(() => destroyGraphView(null));
  assert.doesNotThrow(() => destroyGraphView(undefined));
});

test("relayout delegates to the underlying implementation while alive", () => {
  let relayoutCalls = 0;
  const renderer = {
    kill: () => {},
    relayout: () => { relayoutCalls += 1; },
  };
  const view = createSigmaGraphView(renderer);
  view.relayout();
  view.relayout();
  assert.equal(relayoutCalls, 2);
});

test("radial relayout delegates to the injected relayout callback while alive", () => {
  let calls = 0;
  const chart = { dispose: () => {} };
  const view = createRadialGraphView(chart, () => { calls += 1; });
  view.relayout();
  view.relayout();
  assert.equal(calls, 2);
});

test("relayout after destroy is a no-op", () => {
  let relayoutCalls = 0;
  const renderer = {
    kill: () => {},
    relayout: () => { relayoutCalls += 1; },
  };
  const view = createSigmaGraphView(renderer);
  view.destroy();
  view.relayout();
  assert.equal(relayoutCalls, 0);
});

test("radial relayout after destroy is a no-op", () => {
  let calls = 0;
  const chart = { dispose: () => {} };
  const view = createRadialGraphView(chart, () => { calls += 1; });
  view.destroy();
  view.relayout();
  assert.equal(calls, 0);
});
