/**
 * 报价概况。静态文案，插在报价节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'quote-summary',
  Vue.defineComponent({
    name: 'QuoteSummary',
    template: `
      <section class="quote-summary">
        <div class="quote-summary__head">
          <strong class="quote-summary__title">报价概况</strong>
          <span class="quote-summary__aside">
            合计 43.1 GWh ·
            <span class="quote-summary__green">已完成 27.6 GWh</span>
            · 进行中 15.5 GWh
          </span>
        </div>
        <div>阶段进度：已完成 27.6 GWh（64.0%）；进行中 15.5 GWh（36.0%）</div>
        <div>
          <span class="quote-summary__green">已完成 27.6 GWh（64.0%）</span>：
          <span class="quote-summary__green">已完成 27.6 GWh</span>
        </div>
        <div>
          进行中 15.5 GWh（36.0%）：
          <span class="quote-summary__red">超7天 4.7 GWh</span>
          ·
          <span class="quote-summary__orange">5~7天 5.4 GWh</span>
          ·
          <span class="quote-summary__green">小于5天 5.4 GWh</span>
        </div>
        <div class="quote-summary__note">
          报价阶段用时超过7天计超期，5~7天临期，小于5天正常。
        </div>
      </section>
    `,
  })
)
