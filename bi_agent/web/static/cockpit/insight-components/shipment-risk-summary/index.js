const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent('shipment-risk-summary', createStageRiskComponent({
  name: 'ShipmentRiskSummary',
  fallbackStage: '发货',
}))
