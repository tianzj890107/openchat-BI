/**
 * 订货风险概况。插在订单接收节点联动展示模版顶部。
 * 概览数字来自订单环节证据事实，风险、原因和建议来自真实分析结果。
 */
const { loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'order-risk-summary',
  Vue.defineComponent({
    name: 'OrderRiskSummary',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="order-risk-summary" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <article class="order-risk-summary__card">
            <div class="order-risk-summary__head">
              <strong class="order-risk-summary__title">订货风险概况</strong>
              <span class="order-risk-summary__aside">{{ contextLine }}</span>
            </div>
            <div v-for="item in facts" :key="item.id">
              {{ item.label }}：
              <span :class="item.label.includes('取消') || item.label.includes('减少') ? 'order-risk-summary__red' : 'order-risk-summary__green'">
                {{ metricValue(item) }}
              </span>
            </div>
            <div class="order-risk-summary__note">真实分析摘要：{{ summary }}</div>
          </article>

          <article class="order-risk-summary__panel order-risk-summary__panel--risk">
            <div class="order-risk-summary__title">
              <span class="order-risk-summary__mark--risk">【风险】</span>
              当前订单环节识别 {{ causes.length }} 项风险线索
            </div>
            <div v-for="cause in causes" :key="cause.id">
              <span class="order-risk-summary__num--risk">{{ causeStatus(cause) }}：</span>{{ cause.title }}
            </div>
          </article>

          <article class="order-risk-summary__panel order-risk-summary__panel--cause">
            <div class="order-risk-summary__title">
              <span class="order-risk-summary__mark--cause">【原因】</span>
              证据记录中的原因链
            </div>
            <div v-for="cause in causes" :key="'cause-' + cause.id">
              <span class="order-risk-summary__num--cause">{{ causeMeta(cause) }}：</span>{{ cause.description }}
            </div>
          </article>

          <article class="order-risk-summary__panel order-risk-summary__panel--suggest">
            <div class="order-risk-summary__title">
              <span class="order-risk-summary__mark--suggest">【建议】</span>
              按证据链逐项关闭
            </div>
            <div v-for="action in openRecommendations" :key="action.id">
              {{ action.action }}（{{ action.ownerRole }}；验收：{{ action.acceptance }}）
            </div>
          </article>
        </template>
      </section>
    `,
  })
)
