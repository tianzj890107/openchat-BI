/**
 * 订货风险概况。插在订单接收节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'order-risk-summary',
  Vue.defineComponent({
    name: 'OrderRiskSummary',
    template: `
      <section class="order-risk-summary">
        <article class="order-risk-summary__card">
          <div class="order-risk-summary__head">
            <strong class="order-risk-summary__title">订货风险概况</strong>
            <span class="order-risk-summary__aside">
              合计 71.6 GWh（251.0 亿元） ·
              <span class="order-risk-summary__green">已签单 69.3 GWh（243.0 亿元）</span>
              ·
              <span class="order-risk-summary__orange">已中标未签单 2.3 GWh（8.0 亿元）</span>
            </span>
          </div>
          <div>签单状态：已签单 69.3 GWh（243.0 亿元）；已中标未签单 2.3 GWh（8.0 亿元）</div>
          <div>
            已签单 69.3 GWh（243.0 亿元）：
            <span class="order-risk-summary__green">有效订单 67.3 GWh</span>
            ·
            <span class="order-risk-summary__red">订单取消 1.2 GWh</span>
            ·
            <span class="order-risk-summary__orange">变更减少 0.8 GWh</span>
          </div>
          <div>
            已中标未签单 2.3 GWh（8.0 亿元）：
            <span class="order-risk-summary__orange">已中标未签单 2.3 GWh</span>
          </div>
          <div class="order-risk-summary__note">
            已签单按变更前 69.3 GWh（243.0 亿元）统计；扣除取消与减量 2.0 GWh（7.0 亿元）后，有效订单为 67.3 GWh（236.0 亿元），与全局经营看板已签单口径一致。
          </div>
        </article>

        <article class="order-risk-summary__panel order-risk-summary__panel--risk">
          <div class="order-risk-summary__title">
            <span class="order-risk-summary__mark--risk">【风险】</span>
            订单取消与减量影响约 7.0 亿元出货
          </div>
          <div>
            订单取消 <span class="order-risk-summary__num--risk">1.2 GWh</span>、变更减少
            <span class="order-risk-summary__num--risk">0.8 GWh</span>，合计减少
            <span class="order-risk-summary__num--risk">2.0 GWh / 约 7.0 亿元</span>。变更增加
            <span class="order-risk-summary__num--risk">0.3 GWh</span> 另列，不抵消风险总额。
          </div>
        </article>

        <article class="order-risk-summary__panel order-risk-summary__panel--cause">
          <div class="order-risk-summary__title">
            <span class="order-risk-summary__mark--cause">【原因】</span>
            客户项目调整与技术规格变化
          </div>
          <div>
            取消订单涉及 <span class="order-risk-summary__num--cause">4.2 亿元</span>，主要是客户项目延期与预算调整；订单减量涉及
            <span class="order-risk-summary__num--cause">2.8 亿元</span>，主要是分期建设与技术规格变化。
          </div>
        </article>

        <article class="order-risk-summary__panel order-risk-summary__panel--suggest">
          <div class="order-risk-summary__title">
            <span class="order-risk-summary__mark--suggest">【建议】</span>
            逐单确认变更并补足年内交付
          </div>
          <div>
            销售运营核实取消与减量的生效订单，各产品部与客户确认替代需求；PMC 同步调整排产和发货预测，避免继续按原订单安排产能。
          </div>
        </article>
      </section>
    `,
  })
)
