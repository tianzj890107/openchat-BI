/**
 * 投标概况。静态文案，插在投标节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'bid-summary',
  Vue.defineComponent({
    name: 'BidSummary',
    template: `
      <section class="bid-summary">
        <div class="bid-summary__head">
          <strong class="bid-summary__title">投标概况</strong>
          <span class="bid-summary__aside">
            合计 37.6 GWh ·
            <span class="bid-summary__green">已完成 8.9 GWh</span>
            · 进行中 28.7 GWh
          </span>
        </div>
        <div>阶段进度：已完成 8.9 GWh（23.7%）；进行中 28.7 GWh（76.3%）</div>
        <div>
          已完成 8.9 GWh（23.7%）：
          <span class="bid-summary__green">中标 3.7 GWh</span>
          ·
          <span class="bid-summary__red">丢标 4.1 GWh</span>
          ·
          <span class="bid-summary__gray">弃标 1.1 GWh</span>
        </div>
        <div>
          进行中 28.7 GWh（76.3%）：
          <span class="bid-summary__orange">进行中 28.7 GWh</span>
        </div>
        <div class="bid-summary__note">
          中标 3.7 GWh（13.0 亿元）= 已签单 1.4 GWh（5.0 亿元）+ 已中标未签单 2.3 GWh（8.0 亿元）；丢标 4.1 GWh（14.4 亿元），弃标 1.1 GWh。中标率 49.0% 按项目数 24/49 项计算。
        </div>
      </section>
    `,
  })
)
