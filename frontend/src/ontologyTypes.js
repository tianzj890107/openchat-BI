// Aligned with demo2 /ontology/home's published type palette; retain legacy
// Activity/Process/EntityRelation/MetaRelation instead of conflating them.
export const ONTOLOGY_TYPES = [
  ["BusinessObject", "business_object", "businessObject", "#2563eb", 15, "业务对象"],
  ["LogicalEntity", "logical_entity", "logicalEntity", "#7c3aed", 10, "逻辑实体"],
  ["BusinessAttribute", "attribute", "businessAttribute", "#22c55e", 4, "业务属性"],
  ["Indicator", "metric", "metric", "#4f46e5", 7, "指标"],
  ["BusinessRule", "rule", "businessRule", "#0284c7", 7, "业务规则"],
  ["Term", "term", "term", "#0f766e", 7, "术语"],
  ["Dimension", "dimension", "dimension", "#166534", 7, "维度"],
  ["DimensionDerivedRule", "dimension_derived_rule", "dimensionDerivedRule", "#65a30d", 6, "维度派生规则"],
  ["Action", "action", "action", "#ea580c", 7, "动作"],
  ["Event", "event", "event", "#c026d3", 7, "事件"],
  ["Status", "status", "status", "#57534e", 7, "状态"],
  ["PhysicalTable", "table_node", "tableNode", "#334155", 5, "物理表"],
  ["Field", "column", "column", "#94a3b8", 4, "字段"],
  ["Activity", "activity", "activity", "#16a34a", 7, "活动"],
  ["Process", "process", "process", "#ca8a04", 7, "流程"],
  ["EntityRelation", "relation", "entityRelation", "#9333ea", 6, "实体关系"],
  ["MetaRelation", "meta_relation", "metaRelation", "#475569", 6, "元模型关系"],
];
const aliases = Object.fromEntries(ONTOLOGY_TYPES.flatMap(([type, kind]) => [[type.toLowerCase(), type], [kind, type]]));
Object.assign(aliases, {
  rule: "BusinessRule", business_rule: "BusinessRule", indicator: "Indicator", business_attribute: "BusinessAttribute",
  tablenode: "PhysicalTable", physical_table: "PhysicalTable", column: "Field", relation: "EntityRelation",
});
export const canonicalOntologyType = (type) => aliases[String(type || "").toLowerCase()] || type || "Ontology";
export const ontologyTypeKind = (type) => ONTOLOGY_TYPES.find(([name]) => name === canonicalOntologyType(type))?.[1] || type;
