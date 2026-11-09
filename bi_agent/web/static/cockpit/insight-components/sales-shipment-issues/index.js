/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 * 内容由跨环节共同分析的真实分析结果、证据事实和记录驱动。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime
const { computed } = window.Vue

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'sales-shipment-issues',
  Vue.defineComponent({
    name: 'SalesShipmentIssues',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      // The card may only render causes delivered by the analysis contract.
      // Missing causes stay explicit through the summary/limitations instead of
      // being filled with demo-time placeholder findings.
      const displayCauses = computed(() => insight.causes.value)
      const riskCounts = computed(() => props.slotProps?.riskCounts || {})
      const hasUnifiedRiskCounts = computed(() => Boolean(riskCounts.value?.sales || riskCounts.value?.shipment))
      const salesRiskCount = computed(() => Math.max(0, Number(riskCounts.value?.sales?.count) || 0))
      const shipmentRiskCount = computed(() => Math.max(0, Number(riskCounts.value?.shipment?.count) || 0))
      const riskFindings = computed(() => {
        const seen = new Set(), result = []
        for (const domain of ['sales', 'shipment']) {
          for (const finding of riskCounts.value?.[domain]?.findings || []) {
            const key = String(finding?.riskKey || finding?.id || `${domain}:${finding?.title || result.length}`)
            if (seen.has(key)) continue
            seen.add(key)
            result.push({...finding, riskDomain: finding?.riskDomain || domain})
          }
        }
        return result
      })
      return {...insight, displayCauses, hasUnifiedRiskCounts, salesRiskCount, shipmentRiskCount, riskFindings}
    },
    template: `
      <section class="sales-shipment-issues" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error' && !slotProps.frozenControls" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error' || slotProps.frozenControls" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span class="cockpit-analysis-meta">
              <span v-if="hasResult || !slotProps.frozenControls">{{ stateText }}</span>
              <span v-else>{{ slotProps.frozenControls.state.period }} 年度分析</span>
              <template v-if="slotProps.frozenControls">
                <button class="cockpit-frozen-release__action" type="button" :disabled="slotProps.frozenControls.state.running" @click="slotProps.frozenControls.refresh">{{ slotProps.frozenControls.state.visible ? '重新分析' : '分析' }}</button>
                <span v-if="slotProps.frozenControls.state.running">后台更新中</span>
              </template>
            </span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="sales-shipment-issues__title">销售额 / 出货量共同问题分析：</div>
          <div class="sales-shipment-issues__line sales-shipment-issues__summary" :title="summary">分析摘要：{{ summary }}</div>
          <div v-if="hasUnifiedRiskCounts" class="sales-shipment-issues__counts">
            <span>销售额重点风险 <b>{{ salesRiskCount }}</b> 条</span>
            <span>出货量重点风险 <b>{{ shipmentRiskCount }}</b> 条</span>
          </div>
          <details open v-if="riskFindings.length" class="sales-shipment-issues__details">
            <summary>重点风险 · {{ riskFindings.length }} 项</summary>
            <div v-for="(finding, index) in riskFindings" :key="finding.riskKey || finding.id || index" class="sales-shipment-issues__line">
              {{ index + 1 }}）【{{ finding.riskDomain === 'shipment' ? '出货量风险' : '销售额风险' }}】
              <span class="sales-shipment-issues__num">{{ finding.title }}</span>
              <template v-if="finding.description">——{{ finding.description }}</template>
            </div>
          </details>
          <details open v-if="displayCauses.length" class="sales-shipment-issues__details">
            <summary>原因与待核实项 · {{ displayCauses.length }} 项</summary>
            <div v-for="(cause, index) in displayCauses" :key="cause.id" class="sales-shipment-issues__line">
              {{ index + 1 }}）【{{ causeStatus(cause) }}】
              <span class="sales-shipment-issues__num">{{ cause.title }}</span>——{{ cause.description }}
            </div>
          </details>
          <a v-if="evidenceLink" :href="evidenceLink" target="_blank" rel="noopener" class="insight-evidence-link">查看完整证据</a>
        </template>
      </section>
    `,
  })
)
