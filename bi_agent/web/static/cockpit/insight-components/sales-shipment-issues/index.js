/**
 * 销售额 / 出货量共同问题分析。插在穿透式问题分析的经营指标分组下方。
 * 内容由跨环节共同分析的真实分析结果、证据事实和记录驱动。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight, highlightNumbers } = window.InsightRuntime

loadInsightStyle(import.meta.url)

const NumberText = Vue.defineComponent({
  name: 'NumberText',
  props: {text: {type: String, default: ''}},
  computed: {parts() { return highlightNumbers(this.text) }},
  template: `<template v-for="(part, index) in parts" :key="index"><span v-if="part.num" class="sales-shipment-issues__num">{{ part.text }}</span><template v-else>{{ part.text }}</template></template>`,
})

registerInsightComponent(
  'sales-shipment-issues',
  Vue.defineComponent({
    name: 'SalesShipmentIssues',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading, NumberText},
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
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
          <div class="sales-shipment-issues__title">销售额／出货量共同问题分析：</div>
          <div v-if="summary" class="sales-shipment-issues__line sales-shipment-issues__summary" :title="summary"><number-text :text="summary" /></div>
          <div v-for="(dimension,index) in analysisDimensions" :key="dimension.id" class="sales-shipment-issues__line">
            <span class="sales-shipment-issues__num">{{ index+1 }}</span>）<span class="sales-shipment-issues__num">【{{ dimension.stageLabel }}】</span><number-text v-if="dimension.title !== dimension.stageLabel" :text="dimension.title" /><template v-if="dimension.description">——<number-text :text="dimension.description" /></template>
          </div>
        </template>
      </section>
    `,
  })
)
