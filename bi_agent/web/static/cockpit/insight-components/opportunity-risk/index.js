const { loadInsightStyle, registerInsightComponent, createStageRiskComponent } = window.InsightRuntime

loadInsightStyle(import.meta.url)

// 商机获取 · 销售额口径明细（本体 1117 BR-V02～V05）：总标题“商机当前风险判断及根因分析”，
// 分类标题加“及根因分析”并加粗醒目，不显示分类汇总行；每条风险下的根因默认展开，
// 风险与根因的证据暂时隐藏；建议暂时隐藏。
registerInsightComponent('opportunity-risk', createStageRiskComponent({
  name: 'OpportunityRisk',
  fallbackStage: '商机获取',
  headTitle: '商机当前风险判断及根因分析',
  groupTitleSuffix: '及根因分析',
  groupSummaries: false,
  sectionSummaries: false,
  causesUnderRisks: true,
  causesOpen: true,
  showEvidence: false,
  showRecommendations: false,
}))
