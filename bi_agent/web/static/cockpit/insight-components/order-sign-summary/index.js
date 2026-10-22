/**
 * 订单签单概况。静态文案，插在订单接收节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'order-sign-summary',
  Vue.defineComponent({
    name: 'OrderSignSummary',
    template: `
      <section class="order-sign-summary">
        <div class="order-sign-summary__head">
          <strong class="order-sign-summary__title">订单签单概况</strong>
          <span class="order-sign-summary__aside">总电量 69.6 GWh · 对应 244.0 亿元</span>
        </div>
        <div>
          <span class="order-sign-summary__green">已签单 236.0 亿元 / 67.3 GWh</span>；
          <span class="order-sign-summary__orange">已中标未签单 8.0 亿元 / 2.3 GWh</span>，待完成合同签署。
        </div>
      </section>
    `,
  })
)
