const { computed, ref } = window.Vue

export function cockpitApiBase() {
  const configured = document.querySelector('meta[name="cockpit-api-base"]')?.content || ''
  if (configured) return configured.replace(/\/$/, '')
  const root = location.pathname.replace(/\/cockpit(?:\/(?:home|overview|operations|analysis))?\/?$/, '')
  return `${root}/api/cockpit`
}

export function cockpitIdentityId() {
  const value = Number(new URLSearchParams(location.search).get('id'))
  return value === 2 ? 2 : 1
}

export const InsightLoading = Vue.defineComponent({
  name: 'InsightLoading',
  props: {kind: {type:String,default:'summary'},progress: {type:String,default:''}},
  template: `<div class="insight-loading" :class="'insight-loading--'+kind" role="status" aria-busy="true" aria-label="AI正在分析当前筛选范围">
    <div class="insight-loading__head"><span class="insight-loading__spark">✦</span><strong>{{ progress || 'AI 正在分析' }}</strong><span class="insight-loading__dots">···</span></div>
    <div class="insight-loading__line"></div><div class="insight-loading__line insight-loading__line--short"></div>
    <template v-if="kind==='risk' || kind==='task'"><div class="insight-loading__panel"><div class="insight-loading__line"></div><div class="insight-loading__line insight-loading__line--short"></div></div><div class="insight-loading__line"></div></template>
  </div>`,
})

export const insightProps = {
  analysis: { type: Object, default: null },
  status: { type: String, default: 'idle' },
  progress: { type: String, default: '' },
  refreshing: { type: Boolean, default: false },
  cached: { type: Boolean, default: false },
  stale: { type: Boolean, default: false },
  scopeNotice: { type: String, default: '' },
  error: { type: String, default: '' },
  context: { type: Object, default: () => ({}) },
  slotProps: { type: Object, default: () => ({}) },
}

function number(value) {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function metricValue(metric) {
  if (!metric) return '未提供'
  if (metric.value === null || metric.value === undefined) return metric.claim ? '' : metric.label || '未提供'
  return `${metric.value}${metric.unit ? ` ${metric.unit}` : ''}`
}

export function useInsight(props, emit) {
  const result = computed(() => props.analysis?.result || null)
  const bundle = computed(() => props.analysis?.evidence || {})
  const facts = computed(() => bundle.value.facts || [])
  const records = computed(() => bundle.value.records || [])
  const evidence = computed(() => bundle.value.evidence || [])
  const causes = computed(() => result.value?.causes || [])
  const recommendations = computed(() => result.value?.recommendations || [])
  const limitations = computed(() => result.value?.limitations || bundle.value.limitations || [])
  const summary = computed(() => result.value?.summary || '')
  const hasResult = computed(() => Boolean(result.value))
  const stageName = computed(() => props.context?.stageName || props.analysis?.context?.stageName || '')
  const period = computed(() => props.analysis?.context?.engine==='main' ? '' : props.context?.period || props.analysis?.context?.period || '')
  const department = computed(() => props.analysis?.context?.engine==='main' ? '当前筛选范围' : props.context?.department || props.analysis?.context?.department || '')
  const contextLine = computed(() => [stageName.value, period.value, department.value].filter(Boolean).join(' · '))
  const evidenceCount = computed(() => evidence.value.length)
  const updatedAt = computed(() => {
    const timestamp = Number(props.analysis?.updatedAt)
    if (!Number.isFinite(timestamp)) return ''
    return new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false })
  })
  const stateText = computed(() => {
    if (props.status === 'running') return props.progress || '正在读取真实证据并调用模型分析'
    if (props.status === 'error') return props.error || '真实分析失败'
    if (!hasResult.value) return '等待真实分析结果'
    return `${props.cached || props.refreshing ? '上次分析 · ' : ''}${contextLine.value || '当前环节'} · ${evidenceCount.value} 条证据${updatedAt.value ? ` · ${updatedAt.value}` : ''}`
  })

  function fact(label) {
    const query = String(label || '').toLowerCase()
    return facts.value.find(item => String(item.label || '').toLowerCase().includes(query)) || null
  }

  function factText(label) {
    return metricValue(fact(label))
  }

  function sumFacts(selector, unit) {
    const values = facts.value
      .filter(item => !unit || item.unit === unit)
      .filter(item => !selector || selector(item))
      .map(item => number(item.value)).filter(value => value !== null)
    return values.length ? Number(values.reduce((a,b) => a+b,0).toFixed(10)) : '—'
  }

  function factSum(fragment, unit) {
    const query = String(fragment || '').toLowerCase()
    return sumFacts(item => String(item.label || '').toLowerCase().includes(query), unit)
  }

  function percent(part, total) {
    const p = number(part)
    const t = number(total)
    return p !== null && t ? `${(p / t * 100).toFixed(1)}%` : '—'
  }

  function evidenceFor(cause) {
    const ids = new Set(cause?.evidenceIds || [])
    return evidence.value.filter(item => ids.has(item.id))
  }

  function recordsFor(cause) {
    return evidenceFor(cause).map(item => item.record).filter(Boolean)
  }

  function causeStatus(cause) {
    const labels = {verified:'记录支持', fact:'异常表现', structure:'结构定位', data_gap:'数据缺口', hypothesis:'待验证假设'}
    if (cause?.kind && labels[cause.kind]) return labels[cause.kind]
    return cause?.status === 'supported' ? '记录支持' : '待核实'
  }

  function causeMeta(cause) {
    const linked = evidenceFor(cause)
    return `${causeStatus(cause)} · ${linked.length} 条证据`
  }

  function retry() {
    emit('retry')
  }

  const dismissed = ref([])
  const expanded = ref([])
  const openRecommendations = computed(() => recommendations.value.filter(item => !dismissed.value.includes(item.id)))

  function dismissRecommendation(id) {
    dismissed.value = [...dismissed.value, id]
  }

  function deadlineText(item) {
    const days = Number(item?.deadlineDays)
    if (Number.isFinite(days) && days > 0) return `${days} 个工作日`
    return item?.deadline || '期限未提供'
  }

  function recommendationDetail(item) {
    return item?.detail || item?.acceptance || ''
  }

  function hasRecommendationDetail(item) {
    return Boolean(item?.detail && item.detail !== item.acceptance)
  }

  function toggleRecommendationDetail(id) {
    expanded.value = expanded.value.includes(id) ? expanded.value.filter(item => item !== id) : [...expanded.value, id]
  }

  function isRecommendationExpanded(id) {
    return expanded.value.includes(id)
  }

  return {
    result,
    bundle,
    facts,
    records,
    evidence,
    causes,
    recommendations,
    openRecommendations,
    limitations,
    summary,
    hasResult,
    stageName,
    period,
    department,
    contextLine,
    evidenceCount,
    updatedAt,
    stateText,
    fact,
    factText,
    sumFacts,
    factSum,
    percent,
    evidenceFor,
    recordsFor,
    causeStatus,
    causeMeta,
    metricValue,
    retry,
    dismissRecommendation,
    deadlineText,
    recommendationDetail,
    hasRecommendationDetail,
    toggleRecommendationDetail,
    isRecommendationExpanded,
  }
}

export function createStageRiskComponent(options = {}) {
  return Vue.defineComponent({
    name: options.name || 'StageRiskAnalysis',
    props: insightProps,
    components: {InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const displayStage = computed(() => insight.stageName.value || options.fallbackStage || '当前环节')
      return { ...insight, displayStage }
    },
    template: `
      <section class="stage-risk-analysis" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="risk" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <article class="stage-risk-analysis__card stage-risk-analysis__overview">
            <div class="stage-risk-analysis__head">
              <strong class="stage-risk-analysis__title">{{ displayStage }}风险概况</strong>
              <span class="stage-risk-analysis__aside">{{ contextLine }}</span>
            </div>
            <div v-if="facts.length && facts.length <= 4" class="stage-risk-analysis__facts">
              <div v-for="item in facts" :key="item.id" class="stage-risk-analysis__fact" :title="item.definition || item.label">
                <span>{{ item.label }}</span>
                <b>{{ metricValue(item) }}</b>
              </div>
            </div>
            <details v-else-if="facts.length" class="stage-risk-analysis__facts-fold">
              <summary>查看 {{ facts.length }} 项指标明细</summary>
              <div class="stage-risk-analysis__facts">
                <div v-for="item in facts" :key="item.id" class="stage-risk-analysis__fact" :title="item.definition || item.label">
                  <span>{{ item.label }}</span>
                  <b>{{ metricValue(item) }}</b>
                </div>
              </div>
            </details>
            <div class="stage-risk-analysis__note">
              {{ records.length }} 条记录 · {{ evidenceCount }} 条证据<span v-if="updatedAt"> · {{ updatedAt }}</span>
            </div>
          </article>

          <article class="stage-risk-analysis__card stage-risk-analysis__card--risk stage-risk-analysis__panel">
            <div class="stage-risk-analysis__title">
              <span class="stage-risk-analysis__mark stage-risk-analysis__mark--risk">【风险】</span>
              {{ displayStage }}当前风险判断
            </div>
            <div class="stage-risk-analysis__summary" :title="summary">{{ summary }}</div>
          </article>

          <article class="stage-risk-analysis__card stage-risk-analysis__card--cause stage-risk-analysis__panel">
            <div class="stage-risk-analysis__title">
              <span class="stage-risk-analysis__mark stage-risk-analysis__mark--cause">【原因】</span>
              <template v-if="causes.length">模型基于当前证据识别 {{ causes.length }} 项原因</template>
              <template v-else-if="status === 'limited'">证据范围不足，未形成原因判断</template>
              <template v-else>暂未识别到有证据支持的原因</template>
            </div>
            <div v-if="!causes.length" class="insight-runtime-empty">
              {{ status === 'limited' ? '当前环节缺少匹配指标或同源明细，不能把其他环节数据当作原因证据。' : '当前证据不足以确认原因，需补充同源明细。' }}
            </div>
            <div v-for="(cause, index) in causes" :key="cause.id" class="stage-risk-analysis__cause">
              <span class="stage-risk-analysis__tag stage-risk-analysis__tag--cause">原因{{ index + 1 }}</span>
              <span class="stage-risk-analysis__cause-text">
                <b>{{ cause.title }}</b>——{{ cause.description }}
                <small class="stage-risk-analysis__cause-meta">{{ causeMeta(cause) }}</small>
              </span>
            </div>
          </article>

          <article class="stage-risk-analysis__card stage-risk-analysis__card--suggest stage-risk-analysis__panel">
            <div class="stage-risk-analysis__head">
              <div class="stage-risk-analysis__title">
                <span class="stage-risk-analysis__mark stage-risk-analysis__mark--suggest">【建议】</span>
                按原因形成可执行动作
              </div>
              <span class="stage-risk-analysis__aside">{{ openRecommendations.length }} 项</span>
            </div>
            <div v-if="!openRecommendations.length" class="insight-runtime-empty">
              {{ status === 'limited' ? '证据不足或责任口径未确认，暂无可下发措施；这不代表工作已完成。' : '尚无可交付措施，待原因与责任口径核实。' }}
            </div>
            <div v-for="(item, index) in openRecommendations" :key="item.id" class="stage-risk-analysis__action">
              <span class="stage-risk-analysis__index">{{ index + 1 }}</span>
              <span class="stage-risk-analysis__action-text">{{ item.action }}</span>
              <span class="stage-risk-analysis__owner">{{ item.ownerRole || '未提供' }}</span>
              <span class="stage-risk-analysis__time">{{ deadlineText(item) }}</span>
              <button type="button" class="stage-risk-analysis__close" aria-label="关闭这条建议" @click="dismissRecommendation(item.id)">×</button>
            </div>
            <details class="stage-risk-analysis__foot">
              <summary>查看验收、证据范围与 {{ limitations.length }} 项限制</summary>
              <div v-if="!openRecommendations.length" class="insight-runtime-empty">尚无可交付措施，待原因与责任口径核实。</div>
            <div v-for="(item, index) in openRecommendations" :key="'accept-' + item.id" class="stage-risk-analysis__acceptance">
                建议 {{ index + 1 }} 验收：{{ item.acceptance }}<template v-if="hasRecommendationDetail(item)">；补充：{{ recommendationDetail(item) }}</template>
              </div>
              <div class="stage-risk-analysis__evidence">证据范围：{{ contextLine }}；{{ records.length }} 条记录、{{ evidenceCount }} 条证据。</div>
              <div v-for="(limitation, index) in limitations" :key="'limit-' + index">限制 {{ index + 1 }}：{{ limitation }}</div>
            </details>
          </article>
        </template>
      </section>
    `,
  })
}

export function sumBy(items, selector) {
  return items.reduce((total, item) => total + (number(selector(item)) || 0), 0)
}

export function round(value, digits = 1) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—'
}
