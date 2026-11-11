import {createTaskOrderController, ensureTaskOrderStyle} from './task-order/controller.js'
import {TaskOrderDialog} from './task-order/dialog.js'
import {highlightNumbers} from './number-highlight.js'

export {highlightNumbers}

const { computed, ref } = window.Vue

const NumberText = Vue.defineComponent({
  name: 'StageNumberText',
  props: {text: {type: String, default: ''}},
  computed: {parts() { return highlightNumbers(this.text) }},
  template: `<template v-for="(part, index) in parts" :key="index"><span v-if="part.num" class="stage-risk-analysis__num">{{ part.text }}</span><template v-else>{{ part.text }}</template></template>`,
})

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

const BUSINESS_STAGES={overview:'经营概况',opportunity:'商机获取',quotation:'报价',bid:'投标',contract:'合同签订',order:'订单接收',shipment:'发货'}

export function riskDimensionLinks(dimensions, findings) {
  const riskIndex=new Map(findings.map((f,i)=>[f.id,i+1])), counts=new Map()
  return dimensions.map(d=>({...d,stageLabel:BUSINESS_STAGES[d.stage]||'业务分析',riskLinks:[...new Set(d.findingIds||[])].filter(id=>riskIndex.has(id)).map(id=>{
    const analysisNumber=(counts.get(id)||0)+1;counts.set(id,analysisNumber)
    return {riskId:id,riskNumber:riskIndex.get(id),analysisNumber,label:`风险${riskIndex.get(id)}—原因${analysisNumber}`}
  })}))
}

export function useInsight(props, emit) {
  const result = computed(() => props.analysis?.result || null)
  const bundle = computed(() => props.analysis?.evidence || {})
  const facts = computed(() => bundle.value.facts || [])
  const records = computed(() => bundle.value.records || [])
  const evidence = computed(() => bundle.value.evidence || [])
  const evidenceCounts = computed(() => {
    const counts = bundle.value.counts
    if (counts && Number.isFinite(Number(counts.distinct))) {
      return {
        facts: Number(counts.facts || 0),
        records: Number(counts.records || 0),
        referenced: Number(counts.referenced || 0),
        distinct: Number(counts.distinct || 0),
      }
    }
    const ids = new Set()
    for (const item of evidence.value) if (item && item.id) ids.add(String(item.id))
    return {facts: facts.value.length, records: records.value.length,
      referenced: evidence.value.length, distinct: ids.size || evidence.value.length}
  })
  const evidenceLink = computed(() => {
    const slot=props.slotProps||{};
    if(!slot.frozenControls || !props.analysis?.id)return '';
    const publicationKey=slot.publicationKey||slot.stage;
    return `${slot.apiBase}/ai-publications/stages/${encodeURIComponent(publicationKey)}/evidence?id=${slot.identityId}&format=html&analysisId=${encodeURIComponent(props.analysis.id)}`;
  })
  const findings = computed(() => (result.value?.findings || []).slice(0,4))
  const causes = computed(() => (result.value?.causes || []).map(cause=>({...cause,title:String(cause.title||'').replace(/^\[(待验证假设|结构定位|异常表现|数据缺口|记录支持)\]\s*/, '')})))
  const analysisDimensions = computed(() => riskDimensionLinks(result.value?.analysisDimensions || [],findings.value))
  const recommendations = computed(() => result.value?.recommendations || [])
  const limitations = computed(() => result.value?.caliberNotes || result.value?.limitations || bundle.value.limitations || [])
  const summary = computed(() => result.value?.businessSummary ?? result.value?.summary ?? '')
  const hasResult = computed(() => Boolean(result.value))
  const stageName = computed(() => props.context?.stageName || props.analysis?.context?.stageName || '')
  const period = computed(() => props.analysis?.context?.engine==='main' ? '' : props.context?.period || props.analysis?.context?.period || '')
  const department = computed(() => props.analysis?.context?.engine==='main' ? '当前筛选范围' : props.context?.department || props.analysis?.context?.department || '')
  const contextLine = computed(() => [stageName.value, period.value, department.value].filter(Boolean).join(' · '))
  // Evidence bundles repeat the same record under facts/records/evidence.
  // Count distinct ids so one record is never presented as two findings.
  const evidenceCount = computed(() => evidenceCounts.value.distinct)
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
    const labels = {verified:'记录支持', fact:'异常表现', structure:'结构定位', data_gap:'数据缺口', hypothesis:'分析线索'}
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
    const text = String(item?.deadline || '').trim()
    if (text && text !== '待确认') return text
    const days = Number(item?.deadlineDays)
    if (Number.isFinite(days) && days > 0) return `${days} 个工作日`
    return '期限未提供'
  }

  function displayOwnerRole(value) {
    // Strip only an explicit coordination suffix; keep the role itself.
    return String(value || '').replace(/[（(](?:牵头|协同|配合|支持|执行|负责)[）)]\s*$/u, '').trim()
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
    evidenceLink,
    findings,
    analysisDimensions,
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
    evidenceCounts,
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
    displayOwnerRole,
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
    components: {InsightLoading, TaskOrderDialog, NumberText},
    emits: ['retry'],
    setup(props, { emit }) {
      const insight = useInsight(props, emit)
      const displayStage = computed(() => insight.stageName.value || options.fallbackStage || '当前环节')
      const taskApiBase = computed(() => String(props.slotProps?.apiBase || cockpitApiBase()).replace(/\/$/, ''))
      const taskIdentityId = computed(() => {
        const supplied = Number(props.slotProps?.identityId)
        return supplied === 2 ? 2 : supplied === 1 ? 1 : cockpitIdentityId()
      })
      const analysisId = computed(() => String(props.analysis?.id || ''))
      ensureTaskOrderStyle()
      const taskOrder = createTaskOrderController({
        analysisId, insight, apiBase: () => taskApiBase.value,
        identityId: () => taskIdentityId.value,
      })
      return { ...insight, ...taskOrder, displayStage }
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
          <article v-if="summary || findings.length" class="stage-risk-analysis__card stage-risk-analysis__card--risk stage-risk-analysis__panel">
            <div class="stage-risk-analysis__title">
              <span class="stage-risk-analysis__mark stage-risk-analysis__mark--risk">【风险】</span>
              {{ displayStage }}当前风险判断
            </div>
            <div class="stage-risk-analysis__summary" :title="summary"><number-text :text="summary" /></div>
            <div v-for="(finding,index) in findings" :key="finding.riskKey || finding.id" class="stage-risk-analysis__cause">
              <span class="stage-risk-analysis__tag stage-risk-analysis__mark--risk">风险{{ index+1 }}</span>
              <span class="stage-risk-analysis__cause-text"><b>{{ finding.title }}</b><template v-if="finding.description">——<number-text :text="finding.description" /></template></span>
            </div>
          </article>

          <article v-if="analysisDimensions.length" class="stage-risk-analysis__card stage-risk-analysis__card--cause stage-risk-analysis__panel">
            <div class="stage-risk-analysis__title">
              <span class="stage-risk-analysis__mark stage-risk-analysis__mark--cause">【原因】</span>
              按 {{ analysisDimensions.length }} 个业务环节展开原因分析
            </div>
            <div v-for="(dimension,index) in analysisDimensions" :key="dimension.id" class="stage-risk-analysis__cause">
              <span class="stage-risk-analysis__tag stage-risk-analysis__tag--cause">原因{{ index+1 }}</span>
              <span class="stage-risk-analysis__cause-text"><b>【{{ dimension.stageLabel }}】{{ dimension.title === dimension.stageLabel ? '' : dimension.title }}</b>——<number-text :text="dimension.description" />
                <small class="stage-risk-analysis__cause-meta">{{ dimension.riskLinks.map(link=>link.label).join('；') }} · {{ evidenceFor(dimension).length }} 条证据</small>
              </span>
            </div>
          </article>

          <article v-if="recommendations.length" class="stage-risk-analysis__card stage-risk-analysis__card--suggest stage-risk-analysis__panel">
            <div class="stage-risk-analysis__head">
              <div class="stage-risk-analysis__title">
                <span class="stage-risk-analysis__mark stage-risk-analysis__mark--suggest">【建议】</span>
                核查与改善建议
              </div>
              <div class="stage-risk-analysis__suggest-actions">
                <span class="stage-risk-analysis__aside">{{ openRecommendations.length }} 项</span>
                <button type="button" class="stage-risk-analysis__draft" :disabled="!canCreate"
                        @click="openOrGenerate">{{ taskButtonLabel }}</button>
              </div>
            </div>
            <div v-if="task" class="stage-risk-analysis__task-state" :class="{'stage-risk-analysis__task-state--warn': !taskMatchesSelection}">
              {{ taskStatus }} · {{ task.id }}<template v-if="!taskMatchesSelection"> · 对应上次选择的建议</template>
            </div>
            <div v-if="taskError" class="stage-risk-analysis__error" role="alert">{{ taskError }}</div>
            <div v-if="taskNotice" class="stage-risk-analysis__task-state" role="status">{{ taskNotice }}</div>
            <div v-if="!openRecommendations.length" class="insight-runtime-empty">
              {{ emptyState }}
            </div>
            <div v-else-if="recommendationHint" class="stage-risk-analysis__hint">{{ recommendationHint }}</div>
            <div v-for="(item, index) in openRecommendations" :key="item.id" class="stage-risk-analysis__action">
              <span class="stage-risk-analysis__index">{{ index + 1 }}</span>
              <span class="stage-risk-analysis__action-type" :class="'stage-risk-analysis__action-type--' + (item.actionType || 'pending')">
                {{ actionTypeLabel(item.actionType) }}
              </span>
              <span class="stage-risk-analysis__action-text"><number-text :text="item.action" /></span>
              <span v-if="displayOwnerRole(item.ownerRole)" class="stage-risk-analysis__owner">{{ displayOwnerRole(item.ownerRole) }}</span>
              <span class="stage-risk-analysis__time">{{ deadlineText(item) }}</span>
              <button type="button" class="stage-risk-analysis__close" aria-label="关闭这条建议" @click="dismissRecommendation(item.id)">×</button>
            </div>

          </article>
            <details class="stage-risk-analysis__foot">
              <summary>数据范围、验收与 {{ limitations.length }} 项限制</summary>
            <div v-for="(item, index) in openRecommendations" :key="'accept-' + item.id" class="stage-risk-analysis__acceptance">
                建议 {{ index + 1 }} 验收：<number-text :text="item.acceptance" /><template v-if="hasRecommendationDetail(item)">；补充：<number-text :text="recommendationDetail(item)" /></template>
              </div>
              <a v-if="evidenceLink" :href="evidenceLink" target="_blank" rel="noopener" class="insight-evidence-link">查看完整证据</a>
              <div class="stage-risk-analysis__evidence">证据范围：{{ contextLine }}；{{ evidenceCounts.facts }} 项数值事实、{{ evidenceCounts.records }} 条明细记录、{{ evidenceCounts.referenced }} 条引用证据，去重 {{ evidenceCounts.distinct }} 条。</div>
              <div v-for="(limitation, index) in limitations" :key="'limit-' + index">限制 {{ index + 1 }}：{{ limitation }}</div>
            </details>
          <task-order-dialog v-if="dialogOpen" :task="task" :busy="busy" :error="taskError"
                             :notice="taskNotice" :receipts="receipts" :task-status="taskStatus"
                             :dispatched="dispatched" @close="closeDialog" @save="saveDraft"
                             @dispatch="dispatchDraft" />
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
