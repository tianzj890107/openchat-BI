// Thin lifecycle adapters that hide Sigma/ECharts destruction behind one
// destroy() contract.  Destroy is idempotent: repeated destroyGraphView /
// destroy calls release the underlying instance exactly once, and relayout
// becomes a no-op after the view is destroyed.  This module never touches
// the DOM or the shared radial layout algorithm.

export function createSigmaGraphView(renderer) {
  let destroyed = false;
  return {
    kind: "cluster",
    destroy() {
      if (destroyed) return;
      destroyed = true;
      renderer.kill();
    },
    relayout() {
      if (destroyed) return;
      renderer.relayout();
    },
  };
}

export function createRadialGraphView(chart, relayoutImpl) {
  let destroyed = false;
  return {
    kind: "radial",
    chart,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      chart.dispose();
    },
    relayout() {
      if (destroyed) return;
      relayoutImpl();
    },
  };
}

export function destroyGraphView(view) {
  if (!view) return;
  view.destroy();
}
