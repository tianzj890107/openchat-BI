/**
 * 投标概况。插在投标节点联动展示模版顶部。
 * 只展示当前投标环节证据包中的真实事实与模型分析结论。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'
import { insightProps, useInsight } from '../shared.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'bid-summary',
  Vue.defineComponent({
    name: 'BidSummary',
    props: insightProps,
    emits: ['retry'],
    setup(props, { emit }) {
      return useInsight(props, emit)
    },
    template: `
      <section class="bid-summary" aria-live="polite">
        <div class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="bid-summary__head">
            <strong class="bid-summary__title">投标概况</strong>
            <span class="bid-summary__aside">{{ contextLine }}</span>
          </div>
          <div>
            已出结果金额合计 {{ sumFacts(null, '亿元') }} 亿元 ·
            <span class="bid-summary__green">中标 {{ factText('中标') }}</span>
            · <span class="bid-summary__red">丢标 {{ factText('丢标') }}</span>
          </div>
          <div>
            <span class="bid-summary__green">中标 {{ factText('中标') }}</span>
            ·
            <span class="bid-summary__red">丢标 {{ factText('丢标') }}</span>
            · 快照共 {{ records.length }} 条项目记录、{{ evidenceCount }} 条证据。
          </div>
          <div v-for="cause in causes" :key="cause.id">
            <span class="bid-summary__gray">{{ causeStatus(cause) }}：</span>{{ cause.title }}
          </div>
          <div class="bid-summary__note">真实分析摘要：{{ summary }}</div>
        </template>
      </section>
    `,
  })
)
