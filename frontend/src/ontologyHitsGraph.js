import { createSigmaOntologyRenderer } from "@boulderaitech/ontology-graph";
import { buildGraph } from "./ontologyGraphModel.js";
import { mergeOntologyHitGraphs, ontologyHitKey } from "./ontologyHitsGraphModel.js";

export function mountOntologyHitsGraph({ list, getScope, getScopeVersion, getEntities, getFilters, fetchContext, openEntity }) {
  const host = document.createElement("section");
  host.className = "ontology-hits-graph";
  host.setAttribute("aria-label", "命中本体关系图");
  host.innerHTML = `<p class="ontology-hits-status" role="status"></p>
  <div class="ontology-hits-surface">
    <div class="ontology-hits-canvas" role="img" aria-label="本体关系图，可拖动和缩放，点击节点查看本体"></div>
    <button type="button" class="ontology-hits-reset" data-hit-reset>重置视图</button>
  </div>`;
  list.before(host);
  list.hidden = true;
  const canvas = host.querySelector(".ontology-hits-canvas");
  const status = host.querySelector("[role=status]");
  const surface = host.querySelector(".ontology-hits-surface");
  const scopes = new WeakMap();
  let renderer = null;
  let graph = null;
  let currentData = { nodes: [], links: [] };
  let signature = "";
  let epoch = 0;
  let controller = null;
  let timer;
  let renderedScope = null;
  const visible = () => document.getElementById("view-ontology")?.classList.contains("active");
  const destroy = () => { renderer?.kill(); renderer = null; graph = null; canvas.replaceChildren(); };

  host.querySelector("[data-hit-reset]").addEventListener("click", () => {
    if (host.dataset.incomplete === "true") { signature = ""; void refresh(); }
    else renderer?.instance.getCamera().animatedReset({ duration: 250 });
  });

  async function refresh() {
    clearTimeout(timer);
    if (!visible()) {
      epoch += 1; controller?.abort(); destroy(); signature = "";
      return;
    }
    const scope = getScope();
    const entities = getEntities();
    const filters = getFilters();
    const version = getScopeVersion();
    const nextSignature = JSON.stringify([version, entities.map(ontologyHitKey), filters]);
    if (scope === renderedScope && signature === nextSignature) return;
    renderedScope = scope;
    signature = nextSignature;
    const token = ++epoch;
    controller?.abort();
    const request = new AbortController();
    controller = request;
    destroy();
    list.hidden = true;
    surface.hidden = !entities.length;
    host.dataset.incomplete = "false";
    currentData = { nodes: [], links: [] };
    if (!entities.length) { status.textContent = "当前会话还没有命中本体，分析过程中检索到的本体会在这里组织成图。"; return; }
    let cached = scopes.get(scope);
    if (!cached || cached.version !== version) { cached = { version, contexts: new Map() }; scopes.set(scope, cached); }
    const cache = cached.contexts;
    const pending = entities.filter((entity) => !cache.has(ontologyHitKey(entity)));
    let completed = 0;
    let failed = 0;
    status.textContent = `正在组织 ${entities.length} 个命中本体的关联关系…`;
    // Bound context requests and stop obsolete work when the user leaves/switches.
    await Promise.all(Array.from({ length: Math.min(4, pending.length) }, async () => {
      while (pending.length && !request.signal.aborted) {
        const entity = pending.shift();
        try {
          const context = await fetchContext(entity, request.signal);
          if (!request.signal.aborted) cache.set(ontologyHitKey(entity), context);
        } catch (error) { if (error.name !== "AbortError") failed += 1; }
        completed += 1;
        if (token === epoch) status.textContent = `正在组织本体关联关系 · 已加载 ${completed} 项`;
      }
    }));
    if (token !== epoch || request.signal.aborted || !visible()) return;
    currentData = mergeOntologyHitGraphs(entities, cache, filters);
    host.dataset.incomplete = String(Boolean(failed));
    const hits = currentData.nodes.filter((node) => node.hit).length;
    const incomplete = entities.some((entity) => {
      const context = cache.get(ontologyHitKey(entity));
      return context?.truncated || context?.relation_error || context?.relations_available === false;
    });
    status.textContent = currentData.nodes.length
      ? `${hits} 个命中本体 · ${currentData.nodes.length} 个节点 · ${currentData.links.length} 条关系。高亮为命中本体，按真实关系聚类，点击节点查看本体。${failed ? ` ${failed} 项关系加载失败，已保留命中节点，重置视图可重新加载。` : ""}${incomplete ? " 部分关联数据不可用或已截断，可进入单个本体图继续查看。" : ""}`
      : "当前筛选下没有本体节点，请调整类型筛选。";
    surface.hidden = !currentData.nodes.length;
    if (!currentData.nodes.length) return;
    try {
      graph = buildGraph(currentData);
      renderer = createSigmaOntologyRenderer(canvas, graph);
      renderer.instance.on("clickNode", ({ node }) => {
        const entity = currentData.nodes.find((item) => item.id === node);
        if (entity) openEntity(entity.hit || entity);
      });
    } catch (error) {
      destroy();
      surface.hidden = true;
      list.hidden = false;
      status.textContent = "当前浏览器无法显示关系图，已保留本体列表，可点击查看详情。";
      console.warn("命中本体图渲染失败", error);
    }
  }
  const schedule = () => { clearTimeout(timer); timer = setTimeout(() => void refresh(), 100); };
  // Tear down synchronously on navigation: Sigma's ResizeObserver otherwise
  // sees the now-hidden view before a debounced refresh and rejects its size.
  const onNavigation = () => { if (!visible()) void refresh(); else schedule(); };
  const observer = new MutationObserver(schedule);
  observer.observe(list, { childList: true, subtree: true });
  window.addEventListener("bi-view-changed", onNavigation);
  window.addEventListener("bi-mode-changed", onNavigation);
  window.addEventListener("bi-ontology-filters-changed", schedule);
  schedule();
  return () => {
    clearTimeout(timer); epoch += 1; controller?.abort(); observer.disconnect(); destroy(); host.remove(); list.hidden = false;
    window.removeEventListener("bi-view-changed", onNavigation);
    window.removeEventListener("bi-mode-changed", onNavigation);
    window.removeEventListener("bi-ontology-filters-changed", schedule);
  };
}
