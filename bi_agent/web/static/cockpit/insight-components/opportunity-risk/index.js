const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent('opportunity-risk', createStageRiskComponent({
  name: 'OpportunityRisk',
  fallbackStage: '商机获取',
}))
