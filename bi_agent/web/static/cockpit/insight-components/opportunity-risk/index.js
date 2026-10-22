/**
 * 商机获取的风险、原因、建议。插在商机获取节点联动展示模版顶部。
 */
import { loadInsightStyle, registerInsightComponent } from '../registry.js'

loadInsightStyle(import.meta.url)

registerInsightComponent(
  'opportunity-risk',
  Vue.defineComponent({
    name: 'OpportunityRisk',
    data() {
      return {
        suggestions: [
          {
            id: 1,
            text: '针对 20 家战略客户制定突破计划，分别跟进 7 家无商机与 13 家未进入投标客户',
            owner: '销售 VP（牵头）',
            time: '20 个工作日',
          },
          {
            id: 2,
            text: '推动 13 家已有商机的战略客户进入投标',
            owner: '销售 VP（牵头）',
            time: '20 个工作日',
          },
          {
            id: 3,
            text: '针对 7 个客户限期建立商机',
            owner: '销售 VP（牵头）',
            time: '20 个工作日',
          },
          {
            id: 4,
            text: '对未签单电芯类 50 亿元与 PACK 20 亿元分别制定转化计划，优先保障 AIDC产品部与国内电力产品部两个最大缺口',
            owner: '对应产品部总经理',
            time: '按突破计划协同',
          },
          {
            id: 5,
            text: '9 项技术卡点项目优先排资源、补齐技术输入',
            owner: '方案负责人',
            time: '15 个工作日',
          },
          {
            id: 6,
            text: '战略客户商机推进率与产品部达成率纳入月度经营分析对账',
            owner: '经营管理负责人',
            time: '按月',
          },
        ],
      }
    },
    methods: {
      closeSuggestion(id) {
        this.suggestions = this.suggestions.filter((item) => item.id !== id)
      },
    },
    template: `
      <section class="opportunity-risk">
        <article class="opportunity-risk__card">
          <div class="opportunity-risk__title">
            <span class="opportunity-risk__mark opportunity-risk__mark--risk">【风险】</span>
            商机总量不足；电芯销售与战略客户突破需推进
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--risk">风险1</span>
            <span>
              商机总额（预测）<span class="opportunity-risk__num opportunity-risk__num--risk">280 亿元</span>
              &lt; 全年目标
              <span class="opportunity-risk__num opportunity-risk__num--risk">319 亿元</span>，缺口
              <span class="opportunity-risk__num opportunity-risk__num--risk">39 亿元</span>；其中未签单商机
              <span class="opportunity-risk__num opportunity-risk__num--risk">70 亿元</span>，纳管重点跟踪
              <span class="opportunity-risk__num opportunity-risk__num--risk">180 条 / 44.35 亿元</span>。
            </span>
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--risk">风险2</span>
            <span>
              电芯产品销售待加强推进：未签单电芯类商机
              <span class="opportunity-risk__num opportunity-risk__num--risk">50 亿元</span>，应加快商机转化和订单落地；PACK 未签单商机
              <span class="opportunity-risk__num opportunity-risk__num--risk">20 亿元</span>同步推进。
            </span>
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--risk">风险3</span>
            <span>
              战略客户仍有未突破情况：
              <span class="opportunity-risk__num opportunity-risk__num--risk">20 家</span>战略客户中，
              <span class="opportunity-risk__num opportunity-risk__num--risk">7 家</span>尚无商机，另
              <span class="opportunity-risk__num opportunity-risk__num--risk">13 家</span>已有商机但尚未进入投标。
            </span>
          </div>
        </article>

        <article class="opportunity-risk__card">
          <div class="opportunity-risk__title">
            <span class="opportunity-risk__mark opportunity-risk__mark--cause">【原因】</span>
            战略客户推进不足；方案与报价能力不足；商机承接待加强
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--cause">原因1</span>
            <span>
              战略客户推进不足——
              <span class="opportunity-risk__num opportunity-risk__num--cause">7 家</span>尚无商机，另
              <span class="opportunity-risk__num opportunity-risk__num--cause">13 家</span>已有商机但未进入投标，需逐户核查客户需求与推进责任。
            </span>
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--cause">原因2</span>
            <span>
              方案与报价能力不足，
              <span class="opportunity-risk__num opportunity-risk__num--cause">9 个</span>项目卡在技术方案；五个产品部中，AIDC、国内电力、国际电力的商机预测低于目标；AIDC产品部缺口
              <span class="opportunity-risk__num opportunity-risk__num--cause">35 亿元</span>最大，国内电力缺
              <span class="opportunity-risk__num opportunity-risk__num--cause">23 亿元</span>；构网型、非构网型商机预测分别高于目标
              <span class="opportunity-risk__num opportunity-risk__num--cause">18、11 亿元</span>。
            </span>
          </div>
          <div class="opportunity-risk__row">
            <span class="opportunity-risk__tag opportunity-risk__tag--cause">原因3</span>
            <span>
              未签单商机承接不足——
              <span class="opportunity-risk__num opportunity-risk__num--cause">70 亿元</span>未签单商机中，重点跟踪的
              <span class="opportunity-risk__num opportunity-risk__num--cause">180 条 / 44.35 亿元</span>仅覆盖约
              <span class="opportunity-risk__num opportunity-risk__num--cause">63%</span>；其余
              <span class="opportunity-risk__num opportunity-risk__num--cause">25.65 亿元</span>仍需核实客户需求、预计签约时间与责任人。
            </span>
          </div>
        </article>

        <article class="opportunity-risk__card">
          <div class="opportunity-risk__head">
            <div class="opportunity-risk__title">
              <span class="opportunity-risk__mark opportunity-risk__mark--suggest">【建议】</span>
              按电芯与PACK 商机、战略客户进展分别推进
            </div>
            <button type="button" class="opportunity-risk__draft">生成任务令草稿</button>
          </div>
          <div
            v-for="(item, index) in suggestions"
            :key="item.id"
            class="opportunity-risk__item"
          >
            <span class="opportunity-risk__index">{{ index + 1 }}</span>
            <span class="opportunity-risk__item-text">{{ item.text }}</span>
            <span class="opportunity-risk__owner">{{ item.owner }}</span>
            <span class="opportunity-risk__time">{{ item.time }}</span>
            <button
              type="button"
              class="opportunity-risk__close"
              aria-label="关闭这条建议"
              @click="closeSuggestion(item.id)"
            >×</button>
          </div>
          <div class="opportunity-risk__foot">
            <div>目标：7 家无商机的战略客户建立商机，13 家已有商机的战略客户推进投标；未签单电芯类 50 亿元与 PACK 20 亿元形成逐单转化计划。</div>
            <div>验收：逐户明确目标产品部、目标电量、责任人与时间表；有商机未投标与无商机分别说明原因。按月更新。点击本卡右上角「生成任务令草稿」进入下发；单条建议可点 × 关闭，关闭后不再进入草稿。</div>
          </div>
        </article>

        <article class="opportunity-risk__card opportunity-risk__brief">
          <div>
            商机总额 <span class="opportunity-risk__num opportunity-risk__num--brief">280 亿元</span>（预测金额）&lt; 全年目标
            <span class="opportunity-risk__num opportunity-risk__num--brief">319 亿元</span>、缺口
            <span class="opportunity-risk__num opportunity-risk__num--brief">39 亿元</span>。电芯类商机
            <span class="opportunity-risk__num opportunity-risk__num--brief">230 亿元</span>、PACK 商机
            <span class="opportunity-risk__num opportunity-risk__num--brief">50 亿元</span>；其中电芯已签单
            <span class="opportunity-risk__num opportunity-risk__num--brief">180</span> / 未签单
            <span class="opportunity-risk__num opportunity-risk__num--brief">50 亿元</span>，PACK 已签单
            <span class="opportunity-risk__num opportunity-risk__num--brief">30</span> / 未签单
            <span class="opportunity-risk__num opportunity-risk__num--brief">20 亿元</span>。已签单商机合计
            <span class="opportunity-risk__num opportunity-risk__num--brief">210 亿元</span>（已下订单
            <span class="opportunity-risk__num opportunity-risk__num--brief">191.4 亿元</span>，还有
            <span class="opportunity-risk__num opportunity-risk__num--brief">18.6 亿元</span>订单未进入）；未签单商机合计
            <span class="opportunity-risk__num opportunity-risk__num--brief">70 亿元</span>，其中纳管重点跟踪
            <span class="opportunity-risk__num opportunity-risk__num--brief">180 条 / 44.35 亿元</span>。战略客户中
            <span class="opportunity-risk__num opportunity-risk__num--brief">7 家</span>尚无商机，
            <span class="opportunity-risk__num opportunity-risk__num--brief">13 家</span>已有商机但尚未进入投标。金额为 CRM 商机预测口径；该商机下订单数 ≥1 = 已签单、= 0 = 未签单。
          </div>
        </article>
      </section>
    `,
  })
)
