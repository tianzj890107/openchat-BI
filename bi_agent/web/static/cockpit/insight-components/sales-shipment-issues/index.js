/**
 * 销售额与出货量共同分析。插在穿透式问题分析的经营指标分组下方。
 *
 * 指标 → 问题驱动（不是指标 → 风险）：问题按销售额口径环节分为商机问题、订单问题、
 * 订未发问题三个父节点，每个父节点下列出该环节成立的问题并附分类总结（与销售额口径
 * 明细卡片同一结构）；数据校验不作为问题展示。卡片由本卡片本体规则先判定、规则无法
 * 判定的条目逐条交给模型，只展示总结、问题和证据；根因与建议不属于本交付。
 */
const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent('sales-shipment-issues', createStageRiskComponent({
  name: 'SalesShipmentIssues',
  fallbackStage: '销售额与出货量共同分析',
  headTitle: '销售额与出货量共同分析',
  primaryLabel: '问题',
  // Each parent group carries its own summary, so no per-section summary line.
  sectionSummaries: false,
  showOverallSummary: true,
  showCauses: false,
  showRecommendations: false,
}))
