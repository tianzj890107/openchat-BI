/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 *
 * 指标 → 问题驱动（不是指标 → 风险）：问题分指标异常与数据问题。卡片由本卡片
 * 本体规则先判定、规则无法判定的条目逐条交给模型，展示总结、问题、根因、建议，
 * 以及访问到的本体、规则与取数证据。版式与环节卡片共用，文案为“问题”。
 */
const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent('sales-shipment-issues', createStageRiskComponent({
  name: 'SalesShipmentIssues',
  fallbackStage: '销售额／出货量共同问题',
  primaryLabel: '问题',
  showOverallSummary: true,
}))
