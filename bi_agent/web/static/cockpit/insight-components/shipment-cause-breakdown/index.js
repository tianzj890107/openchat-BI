/**
 * 主因与细分根因。插在发货节点「风险结构与原因拆解」卡片下方。
 * 主因按证据记录中的 cause 聚合，金额和超期天数来自同一条记录。
 */
import {DeepAnalysisDialog} from '../deep-analysis/dialog.js'
import {deepAnalysisPayload} from '../shared.js'

const { loadInsightStyle, registerInsightComponent, insightProps, sumBy, round, useInsight, cockpitApiBase } = window.InsightRuntime

const { computed, ref } = window.Vue

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-cause-breakdown',
  Vue.defineComponent({
    name: 'ShipmentCauseBreakdown',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading, DeepAnalysisDialog},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const groups = computed(() => {
        const grouped = new Map()
        insight.records.value.filter(record => record.causeSupport !== false && record.amount !== null && record.amount !== undefined).forEach(record => {
          const name = record.cause || '未分类'
          const item = grouped.get(name) || {name, amount: 0, count: 0, maxOverdue: 0, items: []}
          item.amount += Number(record.amount) || 0
          item.count += 1
          item.maxOverdue = Math.max(item.maxOverdue, Number(record.overdueDays) || 0)
          item.items.push(record)
          grouped.set(name, item)
        })
        const values = [...grouped.values()].sort((a, b) => b.amount - a.amount)
        if (values.length) return values
        return insight.causes.value.map(cause => ({name: cause.title, amount: null, count: 0, maxOverdue: null, items: [], cause}))
      })
      const totalAmount = computed(() => sumBy(groups.value, item => item.amount))
      const share = value => totalAmount.value ? `${round(value / totalAmount.value * 100, 1)}%` : '—'
      // Each cause group opens the same root-cause workbench as the stage cards.
      const deepAnalysis = ref(null)
      const deepAnalysisRoot = computed(() => String(props.slotProps?.apiBase || cockpitApiBase()).replace(/\/api\/cockpit$/, ''))
      const openCauseDeepAnalysis = group => {
        const result = props.analysis?.result || {}
        const cause = group.cause || {}
        const clause = {
          code: String(cause.causeCode || cause.code || ''),
          title: String(group.name || cause.title || ''),
          description: String(cause.description || ''),
          status: String(cause.statusLabel || cause.status || ''),
          decidedBy: String(cause.decidedBy || ''),
          linkedRisks: (cause.linkedRiskCodes || cause.riskCodes || []).slice(0, 12),
          inferred: Boolean(cause.inferred),
        }
        deepAnalysis.value = {
          item: {title: group.name, description: cause.description || '', stageLabel: props.context?.stageName || '发货'},
          payload: deepAnalysisPayload('cause', clause, {
            period: props.analysis?.period || result.period || props.slotProps?.period || '',
            measurementDate: group.items?.[0]?.measurementDate || '',
            stage: props.context?.stageName || '',
            title: props.slotProps?.title || '',
            ontology: result.trace?.ontology || result.ontology?.name || '',
            slot: props.slotProps?.slotId || '',
            siblings: groups.value.filter(other => other !== group).map(other => ({title: other.name})),
            facts: insight.facts.value,
          }),
        }
      }
      return { ...insight, groups, totalAmount, share, round, deepAnalysis, deepAnalysisRoot, openCauseDeepAnalysis }
    },
    template: `
      <section class="shipment-cause-breakdown" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="summary" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="shipment-cause-breakdown__title">按证据记录聚合的主因与细分根因</div>
          <div v-if="!groups.length" class="insight-runtime-empty">缺少同源明细，暂不能拆分根因与金额占比。</div>
          <div class="shipment-cause-breakdown__grid">
            <article v-for="group in groups" :key="group.name" class="shipment-cause-breakdown__item">
              <div class="shipment-cause-breakdown__item-title">
                {{ plain(group.name) }} ·
                <span class="shipment-cause-breakdown__metric">
                  <template v-if="group.amount !== null">{{ group.count }} 单 / {{ round(group.amount, 1) }} 亿元 / {{ share(group.amount) }}</template><template v-else>待核实</template>
                </span>
                <button type="button" class="shipment-cause-breakdown__deep" title="在对话框中深度分析这组根因" @click="openCauseDeepAnalysis(group)">深度分析</button>
              </div>
              <ul v-if="group.items.length" class="shipment-cause-breakdown__list">
                <li v-for="item in group.items" :key="item.id">
                  {{ item.id }} · {{ item.customer }} · {{ item.evidence }}：
                  <span class="shipment-cause-breakdown__metric">{{ item.amount }} 亿元 / 超期 {{ item.overdueDays }} 天</span>
                </li>
              </ul>
              <div v-else class="insight-runtime-empty">{{ group.cause ? group.cause.description : '记录级主因未提供' }}</div>
            </article>
          </div>
          <div class="shipment-cause-breakdown__foot">
            <template v-if="groups.some(g => g.items.length)">证据记录金额合计 {{ round(totalAmount, 1) }} 亿元。</template>
            真实分析摘要：{{ summary }}
          </div>
        </template>
        <deep-analysis-dialog v-if="deepAnalysis" :open="true" :payload="deepAnalysis.payload"
                              :item="deepAnalysis.item" :root="deepAnalysisRoot" @close="deepAnalysis = null" />
      </section>
    `,
  })
)
