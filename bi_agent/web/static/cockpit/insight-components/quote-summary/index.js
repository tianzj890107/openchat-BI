/**
 * 报价概况。插在报价节点联动展示模版顶部。
 * 阶段数值来自服务端证据事实，分析结论来自当前报价环节的模型结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'quote-summary',
  Vue.defineComponent({
    name: 'QuoteSummary',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="quote-summary" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="quote-summary__head">
            <strong class="quote-summary__title">报价概况</strong>
            <span class="quote-summary__aside">{{ contextLine }}</span>
          </div>
          <div>
            阶段事实合计 {{ sumFacts(null, 'GWh') }} GWh ·
            <span class="quote-summary__green">已完成 {{ factText('已完成') }}</span>
            · 进行中 {{ factSum('进行中', 'GWh') }} GWh
          </div>
          <div>
            阶段进度：已完成 {{ factText('已完成') }}（{{ percent(fact('已完成')?.value, sumFacts(null, 'GWh')) }}）；
            进行中各时限分组合计 {{ factSum('进行中', 'GWh') }} GWh
            （{{ percent(factSum('进行中', 'GWh'), sumFacts(null, 'GWh')) }}）。
          </div>
          <div>
            进行中：
            <span class="quote-summary__red">超7天 {{ factText('超7天') }}</span>
            ·
            <span class="quote-summary__orange">5–7天 {{ factText('5–7天') }}</span>
            ·
            <span class="quote-summary__green">小于5天 {{ factText('小于5天') }}</span>
          </div>
          <div class="quote-summary__note">真实分析摘要：{{ summary }}</div>
        </template>
      </section>
    `,
  })
)
