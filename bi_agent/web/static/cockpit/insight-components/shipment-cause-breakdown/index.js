/**
 * 四类主因与细分根因。插在发货节点「风险结构与原因拆解」卡片下方。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'shipment-cause-breakdown',
  Vue.defineComponent({
    name: 'ShipmentCauseBreakdown',
    template: `
      <section class="shipment-cause-breakdown">
        <div class="shipment-cause-breakdown__title">四类主因与细分根因</div>
        <div class="shipment-cause-breakdown__grid">
          <article class="shipment-cause-breakdown__item">
            <div class="shipment-cause-breakdown__item-title">
              排产问题 · <span class="shipment-cause-breakdown__metric">2.2 GWh / 7.9 亿元 · 32.5%</span>
            </div>
            <ul class="shipment-cause-breakdown__list">
              <li>集团产能池竞标分配不足 / 被调走：<span class="shipment-cause-breakdown__metric">0.6 GWh</span></li>
              <li>需求预测不准 → 未分配产能（产销对齐问题）：<span class="shipment-cause-breakdown__metric">0.6 GWh</span></li>
              <li>排产优先级 / 插单（排队过号）：<span class="shipment-cause-breakdown__metric">0.4 GWh</span></li>
              <li>跨工厂调配受限：<span class="shipment-cause-breakdown__metric">0.3 GWh</span></li>
              <li>信用额度 / 信保限额 / 回款条件未满足而主动控货：<span class="shipment-cause-breakdown__metric">0.3 GWh</span></li>
            </ul>
          </article>
          <article class="shipment-cause-breakdown__item">
            <div class="shipment-cause-breakdown__item-title">
              厂线产能和生产问题 · <span class="shipment-cause-breakdown__metric">2.1 GWh / 7.5 亿元 · 30.9%</span>
            </div>
            <ul class="shipment-cause-breakdown__list">
              <li>物料短缺：电芯 / 正极材料 / 结构件缺料与到料延迟：<span class="shipment-cause-breakdown__metric">0.8 GWh</span></li>
              <li>质量问题：批次异常 / 返工、质检未放行：<span class="shipment-cause-breakdown__metric">1.3 GWh</span></li>
            </ul>
          </article>
          <article class="shipment-cause-breakdown__item">
            <div class="shipment-cause-breakdown__item-title">
              物流及单证问题 · <span class="shipment-cause-breakdown__metric">1.3 GWh / 4.5 亿元 · 18.5%</span>
            </div>
            <ul class="shipment-cause-breakdown__list">
              <li>运力 / 发运排期冲突：<span class="shipment-cause-breakdown__metric">0.4 GWh</span></li>
              <li>海外舱位无法订到：<span class="shipment-cause-breakdown__metric">0.4 GWh</span></li>
              <li>认证与单证（UL、CE、并网）未能提供，无法提货：<span class="shipment-cause-breakdown__metric">0.5 GWh</span></li>
            </ul>
          </article>
          <article class="shipment-cause-breakdown__item">
            <div class="shipment-cause-breakdown__item-title">
              客户侧提货 · <span class="shipment-cause-breakdown__metric">1.3 GWh / 4.4 亿元 · 18.1%</span>
            </div>
            <ul class="shipment-cause-breakdown__list">
              <li>客户项目延期：<span class="shipment-cause-breakdown__metric">0.3 GWh</span></li>
              <li>现场不具备收货条件（场地、并网）：<span class="shipment-cause-breakdown__metric">0.2 GWh</span></li>
              <li>客户改期 / 分批提货：<span class="shipment-cause-breakdown__metric">0.5 GWh</span></li>
              <li>验收争议与售后问题未关闭：<span class="shipment-cause-breakdown__metric">0.3 GWh</span></li>
            </ul>
          </article>
        </div>
        <div class="shipment-cause-breakdown__foot">
          四类主因电量 2.2+2.1+1.3+1.3 = 6.9 GWh，对应金额 7.9+7.5+4.5+4.4 = 24.3 亿元；电量按 319 亿元 = 91 GWh 的模拟比例折算并按 0.1 GWh 展示。
        </div>
      </section>
    `,
  })
)
