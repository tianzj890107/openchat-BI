// Pure ontology subgraph view state (layout/strategy/data/render token).
// The runtime keeps a single state object here and maps transitions to DOM
// side effects.  Every transition that invalidates a mounted render bumps the
// monotonic renderToken; async work captures a token and must confirm it is
// still current before touching the canvas (prevents late mounts/overwrites).
//
// Async tasks are tracked with independent request/render busy flags plus
// monotonic epochs/tokens.  finish transitions are epoch/token-aware so a
// stale request or render can never unlock a newer task's busy lock.

export const ONTOLOGY_LAYOUT_CLUSTER = "cluster";
export const ONTOLOGY_LAYOUT_RADIAL = "radial";
export const ONTOLOGY_STRATEGY_CONTEXT = "context";
export const ONTOLOGY_STRATEGY_EXPAND = "expand";

export const LAYOUT_CLUSTER = ONTOLOGY_LAYOUT_CLUSTER;
export const LAYOUT_RADIAL = ONTOLOGY_LAYOUT_RADIAL;
export const STRATEGY_CONTEXT = ONTOLOGY_STRATEGY_CONTEXT;
export const STRATEGY_EXPAND = ONTOLOGY_STRATEGY_EXPAND;

export function createOntologyGraphViewState() {
  return {
    layout: LAYOUT_CLUSTER,
    strategy: STRATEGY_CONTEXT,
    data: null,
    entity: null,
    open: false,
    requestEpoch: 0,
    renderToken: 0,
    requestBusy: false,
    renderBusy: false,
  };
}

// Opening resets the view to the default relationship-cluster layout so that
// every reopen starts with 关系聚类可视化 (Spec AC-R1).
export function openOntologyGraphView(state, entity) {
  const fresh = createOntologyGraphViewState();
  return {
    ...fresh,
    entity: entity ? { ...entity } : null,
    open: true,
    requestEpoch: fresh.requestEpoch + 1,
    renderToken: fresh.renderToken + 1,
  };
}

// Closing clears every busy flag and invalidates old epochs/tokens so late
// async work can no longer clear or mount anything.
export function closeOntologyGraphView(state) {
  return {
    ...state,
    open: false,
    requestEpoch: state.requestEpoch + 1,
    renderToken: state.renderToken + 1,
    requestBusy: false,
    renderBusy: false,
  };
}

// Layout switching is a pure client-side preference: the loaded graph data is
// kept untouched, no fetch is ever issued, and an in-flight request stays
// busy (only the render side is invalidated).
export function selectOntologyGraphLayout(state, layout) {
  if (state.layout === layout) return state;
  return { ...state, layout, renderToken: state.renderToken + 1 };
}

// A strategy (context/expand) response replaces the graph data while the
// current layout preference is preserved.
export function receiveOntologyGraphData(state, strategy, graph) {
  return {
    ...state,
    strategy,
    data: graph,
    anchor: graph?.anchor ?? null,
    renderToken: state.renderToken + 1,
  };
}

export function isOntologyGraphRenderCurrent(state, token) {
  return Boolean(state && state.open && state.renderToken === token);
}

// --- Async request lifecycle -------------------------------------------
// A request that is superseded by a newer one keeps requestBusy true until
// the newest epoch finishes; finishOntologyGraphRequest is a no-op for any
// epoch other than the current one.
export function beginOntologyGraphRequest(state) {
  return {
    ...state,
    requestEpoch: state.requestEpoch + 1,
    renderToken: state.renderToken + 1,
    requestBusy: true,
  };
}

export function finishOntologyGraphRequest(state, requestEpoch) {
  if (!state.requestBusy || state.requestEpoch !== requestEpoch) return state;
  return { ...state, requestBusy: false };
}

// --- Async render lifecycle --------------------------------------------
export function beginOntologyGraphRender(state) {
  return {
    ...state,
    renderToken: state.renderToken + 1,
    renderBusy: true,
  };
}

export function finishOntologyGraphRender(state, renderToken) {
  if (!state.renderBusy || state.renderToken !== renderToken) return state;
  return { ...state, renderBusy: false };
}

// Busy means any task (fetch or render) is still in flight.
export function isOntologyGraphBusy(state) {
  return Boolean(state && (state.requestBusy || state.renderBusy));
}
