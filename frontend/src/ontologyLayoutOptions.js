// Single source of truth for the ontology subgraph layout picker.
// The runtime builds the select options and the white help tooltip from this
// registry only; neither labels nor hints are duplicated in DOM templates,
// CSS or other runtime constants.

export const ONTOLOGY_LAYOUT_OPTIONS = Object.freeze([
  Object.freeze({
    value: "cluster",
    label: "关系聚类可视化",
    hint: "ForceAtlas2 是一种先进的力导向图布局，适合查看节点之间的关系聚类。",
  }),
  Object.freeze({
    value: "radial",
    label: "语义环形可视化",
    hint: "以当前锚点为中心，按照最短关系距离由内向外分环排列。",
  }),
]);

export function ontologyLayoutOption(value) {
  return ONTOLOGY_LAYOUT_OPTIONS.find((option) => option.value === value) || null;
}
