const { computed, ref } = window.Vue

export const insightProps = {
  analysis: { type: Object, default: null },
  status: { type: String, default: 'idle' },
  progress: { type: String, default: '' },
  error: { type: String, default: '' },
  context: { type: Object, default: () => ({}) },
  slotProps: { type: Object, default: () => ({}) },
}

function number(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function metricValue(metric) {
  if (!metric) return '未提供'
  if (metric.value === null || metric.value === undefined) return metric.label || '未提供'
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
  const period = computed(() => props.context?.period || props.analysis?.context?.period || '')
  const department = computed(() => props.context?.department || props.analysis?.context?.department || '')
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
    return `${contextLine.value || '当前环节'} · ${evidenceCount.value} 条证据${updatedAt.value ? ` · ${updatedAt.value}` : ''}`
  })

  function fact(label) {
    const query = String(label || '').toLowerCase()
    return facts.value.find(item => String(item.label || '').toLowerCase().includes(query)) || null
  }

  function factText(label) {
    return metricValue(fact(label))
  }

  function sumFacts(selector, unit) {
    return facts.value
      .filter(item => !unit || item.unit === unit)
      .filter(item => !selector || selector(item))
      .reduce((total, item) => total + (number(item.value) || 0), 0)
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
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const displayStage = computed(() => insight.stageName.value || options.fallbackStage || '当前环节')
      return { ...insight, displayStage }
    },
    template: `
      <section class="stage-risk-analysis" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <article class="stage-risk-analysis__card stage-risk-analysis__card--risk">
            <div class="stage-risk-analysis__head">
              <div class="stage-risk-analysis__title">
                <span class="stage-risk-analysis__mark stage-risk-analysis__mark--risk">【风险】</span>
                {{ displayStage }}风险概况
              </div>
              <span class="stage-risk-analysis__aside">{{ contextLine }}</span>
            </div>
            <div class="stage-risk-analysis__summary" :title="summary">{{ summary }}</div>
            <div v-if="facts.length" class="stage-risk-analysis__facts">
              <div v-for="item in facts" :key="item.id" class="stage-risk-analysis__fact" :title="item.definition || item.label">
                <span>{{ item.label }}</span>
                <b>{{ metricValue(item) }}</b>
              </div>
            </div>
          </article>

          <article class="stage-risk-analysis__card stage-risk-analysis__card--cause">
            <div class="stage-risk-analysis__head">
              <div class="stage-risk-analysis__title">
                <span class="stage-risk-analysis__mark stage-risk-analysis__mark--cause">【原因】</span>
                模型基于当前证据识别 {{ causes.length }} 项原因
              </div>
            </div>
            <div v-for="(cause, index) in causes" :key="cause.id" class="stage-risk-analysis__cause">
              <div class="stage-risk-analysis__cause-head">
                <span class="stage-risk-analysis__index">{{ index + 1 }}</span>
                <b>{{ cause.title }}</b>
                <span class="stage-risk-analysis__tag">{{ causeMeta(cause) }}</span>
              </div>
              <div class="stage-risk-analysis__cause-text" :title="cause.description">{{ cause.description }}</div>
            </div>
          </article>

          <article class="stage-risk-analysis__card stage-risk-analysis__card--suggest">
            <div class="stage-risk-analysis__head">
              <div class="stage-risk-analysis__title">
                <span class="stage-risk-analysis__mark stage-risk-analysis__mark--suggest">【建议】</span>
                按证据链形成可验收动作
              </div>
              <span class="stage-risk-analysis__aside">{{ openRecommendations.length }} 项</span>
            </div>
            <div v-for="(item, index) in openRecommendations" :key="item.id" class="stage-risk-analysis__action">
              <span class="stage-risk-analysis__index">{{ index + 1 }}</span>
              <div class="stage-risk-analysis__action-main">
                <div class="stage-risk-analysis__action-text">{{ item.action }}</div>
                <div class="stage-risk-analysis__action-meta">
                  <span class="stage-risk-analysis__owner"><em>责任</em>{{ item.ownerRole || '未提供' }}</span>
                  <span class="stage-risk-analysis__deadline"><em>期限</em>{{ deadlineText(item) }}</span>
                  <span class="stage-risk-analysis__acceptance"><em>验收</em>{{ item.acceptance }}</span>
                  <button v-if="hasRecommendationDetail(item)" type="button" class="stage-risk-analysis__detail-toggle"
                          :aria-expanded="String(isRecommendationExpanded(item.id))"
                          @click="toggleRecommendationDetail(item.id)">
                    {{ isRecommendationExpanded(item.id) ? '收起' : '查看详情' }}
                  </button>
                </div>
                <div v-if="isRecommendationExpanded(item.id)" class="stage-risk-analysis__detail">
                  {{ recommendationDetail(item) }}
                </div>
              </div>
              <button type="button" class="stage-risk-analysis__close" aria-label="关闭这条建议" @click="dismissRecommendation(item.id)">×</button>
            </div>
            <details class="stage-risk-analysis__foot">
              <summary>证据范围与 {{ limitations.length }} 项限制</summary>
              <div>证据范围：{{ contextLine }}；{{ records.length }} 条记录、{{ evidenceCount }} 条证据。</div>
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
