const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

// 商机获取 · 销售额口径明细: each risk carries an expandable list of its own
// causes (one risk → many causes); advice is hidden for now.
registerInsightComponent('opportunity-risk', createStageRiskComponent({
  name: 'OpportunityRisk',
  fallbackStage: '商机获取',
  sectionSummaries: false,
  causesUnderRisks: true,
  showRecommendations: false,
}))
