import { canonicalOntologyType as canonicalType, ontologyTypeKind } from "./ontologyTypes.js";
export const ontologyHitType = (entity) => canonicalType(entity.type || entity.kind);
export const ontologyHitKey = (entity) => JSON.stringify([entity.source || "", entity.repository_id || "", ontologyHitType(entity), entity.code]);

// Keep repository/source identities separate, and merge only real returned edges.
// Missing context leaves an isolated hit rather than an invented parent relation.
export function mergeOntologyHitGraphs(entities, contexts, filters = {}) {
  const nodes = new Map();
  const links = new Map();
  const scopeOf = (entity) => JSON.stringify([entity.source || "", entity.repository_id || ""]);
  const nodeKey = (scope, node) => JSON.stringify([scope, canonicalType(node.type), node.code || node.id]);
  for (const entity of entities) {
    const context = contexts.get(ontologyHitKey(entity));
    const scope = scopeOf(entity);
    const localIds = new Map();
    for (const node of context?.nodes || []) {
      const id = nodeKey(scope, node);
      localIds.set(node.id || node.code, id);
      nodes.set(id, { ...node, id, type: canonicalType(node.type), focus: false, anchor: false, source: entity.source, repository_id: entity.repository_id });
    }
    for (const edge of context?.links || []) {
      if (edge.synthetic) continue;
      const source = localIds.get(edge.source);
      const target = localIds.get(edge.target);
      if (!source || !target || source === target) continue;
      const key = JSON.stringify([source, target, edge.relationType || edge.type || edge.label || ""]);
      links.set(key, { ...edge, id: key, source, target });
    }
  }
  for (const entity of entities) {
    const node = { type: ontologyHitType(entity), code: entity.code };
    const id = nodeKey(scopeOf(entity), node);
    nodes.set(id, { ...nodes.get(id), ...node, id, name: entity.name || nodes.get(id)?.name || entity.code,
      source: entity.source, repository_id: entity.repository_id, focus: true, hit: entity });
  }
  const visible = [...nodes.values()].filter((node) => filters[ontologyTypeKind(node.type)] !== false);
  const visibleIds = new Set(visible.map((node) => node.id));
  return { nodes: visible, links: [...links.values()].filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)) };
}
