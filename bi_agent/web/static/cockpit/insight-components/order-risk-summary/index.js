const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent('order-risk-summary', createStageRiskComponent({
  name: 'OrderRiskSummary',
  fallbackStage: '订单接收',
}))
