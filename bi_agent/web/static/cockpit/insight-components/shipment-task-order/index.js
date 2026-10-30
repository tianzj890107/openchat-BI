/**
 * 发货风险解决任务令。插在发货节点「客户与超期订单」卡片下方。
 * 草稿、保存和待办下发都通过服务端任务接口完成；浏览器不持有接收人手机号。
 */
const { cockpitApiBase, cockpitIdentityId, loadInsightStyle, registerInsightComponent, insightProps, useInsight } = window.InsightRuntime

loadInsightStyle(import.meta.url)

const TASK_STATUS = {
  draft: '草稿待确认',
  issued: '已下发',
  accepted: '已接收',
  review: '待验收',
  closed: '已关闭',
}

registerInsightComponent(
  'shipment-task-order',
  Vue.defineComponent({
    name: 'ShipmentTaskOrder',
    props: insightProps,
    components: {InsightLoading: window.InsightRuntime.InsightLoading},
    emits: ['retry'],
    setup(props, { emit }) {
      const { computed, ref } = window.Vue
      const insight = useInsight(props, emit)
      const task = ref(null)
      const dialogOpen = ref(false)
      const busy = ref('')
      const taskError = ref('')
      const taskNotice = ref('')
      const dispatchReceipts = ref([])

      const apiBase = computed(() => String(props.slotProps?.apiBase || cockpitApiBase()).replace(/\/$/, ''))
      const identityId = computed(() => {
        const supplied = Number(props.slotProps?.identityId)
        return supplied === 2 ? 2 : supplied === 1 ? 1 : cockpitIdentityId()
      })
      const analysisId = computed(() => String(props.analysis?.id || ''))
      const canCreate = computed(() => Boolean(analysisId.value && insight.openRecommendations.value.length))
      const taskStatus = computed(() => task.value ? (TASK_STATUS[task.value.status] || task.value.status || '状态未知') : '')
      const dispatched = computed(() => ['issued', 'accepted', 'review', 'closed'].includes(task.value?.status))
      const receipts = computed(() => dispatchReceipts.value.length ? dispatchReceipts.value : (task.value?.dispatch || []))

      function linkedCauseTitles(action) {
        const ids = new Set(action.causeIds || [])
        return insight.causes.value.filter(cause => ids.has(cause.id)).map(cause => cause.title).join('；')
      }

      async function request(path, options = {}) {
        const response = await fetch(`${apiBase.value}${path}`, {
          ...options,
          headers: {Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {})},
        })
        const payload = await response.json().catch(() => null)
        if (!response.ok || !payload) {
          throw new Error(payload?.detail || `任务服务返回 ${response.status}`)
        }
        return payload
      }

      function copyTask(value) {
        return JSON.parse(JSON.stringify(value))
      }

      async function generateDraft() {
        if (!analysisId.value) {
          taskError.value = '当前分析尚未生成，不能创建任务令草稿'
          return
        }
        if (!canCreate.value) {
          taskError.value = '当前分析没有可确认的原因与措施，不能从正文猜测任务令'
          return
        }
        busy.value = 'draft'
        taskError.value = ''
        taskNotice.value = ''
        try {
          const value = await request(`/analyses/${encodeURIComponent(analysisId.value)}/draft`, {method: 'POST', body: '{}'})
          task.value = copyTask(value)
          if (value.status === 'draft') {
            dialogOpen.value = true
            taskNotice.value = '任务令草稿已生成，请核对责任、期限与验收后下发'
          } else {
            taskNotice.value = `任务令${TASK_STATUS[value.status] || value.status || '已提交'}；接收人由服务端安全映射`
          }
        } catch (cause) {
          taskError.value = `生成草稿失败：${cause.message || cause}`
        } finally {
          busy.value = ''
        }
      }

      function openEditor() {
        if (!task.value) {
          generateDraft()
          return
        }
        if (task.value.status !== 'draft') {
          taskError.value = `任务令${taskStatus.value}，不能再次编辑或重复下发`
          return
        }
        taskError.value = ''
        dialogOpen.value = true
      }

      function closeDialog() {
        if (!busy.value) dialogOpen.value = false
      }

      async function persistDraft() {
        if (!task.value || task.value.status !== 'draft') throw new Error('只有草稿状态可以编辑')
        const measures = (task.value.measures || []).map(item => ({
          id: String(item.id || ''),
          action: String(item.action || '').trim(),
          owner: String(item.owner || '').trim(),
          deadline: String(item.deadline || '').trim(),
          acceptance: String(item.acceptance || '').trim(),
        }))
        if (!String(task.value.title || '').trim() || !String(task.value.goal || '').trim() || !measures.length) {
          throw new Error('请补齐标题、目标和至少一项措施')
        }
        if (measures.some(item => !item.action || !item.owner || !item.deadline || !item.acceptance)) {
          throw new Error('每项措施都需要填写动作、责任角色、期限和验收标准')
        }
        const saved = await request(`/tasks/${encodeURIComponent(task.value.id)}`, {
          method: 'POST',
          body: JSON.stringify({
            id: identityId.value,
            revision: task.value.revision,
            action: 'save',
            title: String(task.value.title).trim(),
            goal: String(task.value.goal).trim(),
            measures,
          }),
        })
        task.value = copyTask(saved)
        return saved
      }

      async function saveDraft() {
        busy.value = 'save'
        taskError.value = ''
        taskNotice.value = ''
        try {
          await persistDraft()
          taskNotice.value = '任务令草稿已保存'
        } catch (cause) {
          taskError.value = `保存草稿失败：${cause.message || cause}`
        } finally {
          busy.value = ''
        }
      }

      async function dispatchDraft() {
        busy.value = 'dispatch'
        taskError.value = ''
        taskNotice.value = ''
        try {
          await persistDraft()
          const result = await request(`/tasks/${encodeURIComponent(task.value.id)}/dispatch`, {
            method: 'POST',
            body: JSON.stringify({id: identityId.value, retry: false}),
          })
          dispatchReceipts.value = result.results || []
          if (!result.accepted) {
            throw new Error(result.message || `仅 ${result.acceptedCount || 0}/${result.total || 0} 项成功`)
          }
          if (result.task) task.value = copyTask(result.task)
          else task.value = {...task.value, status: 'issued'}
          dialogOpen.value = false
          taskNotice.value = `${result.message || '任务令已下发'}；接收人由服务端安全映射`
        } catch (cause) {
          taskError.value = `下发失败：${cause.message || cause}`
        } finally {
          busy.value = ''
        }
      }

      return {
        ...insight,
        linkedCauseTitles,
        task,
        dialogOpen,
        busy,
        taskError,
        taskNotice,
        dispatchReceipts,
        taskStatus,
        dispatched,
        receipts,
        canCreate,
        generateDraft,
        openEditor,
        closeDialog,
        saveDraft,
        dispatchDraft,
      }
    },
    template: `
      <section class="shipment-task-order" aria-live="polite">
        <insight-loading v-if="!hasResult && status !== 'error'" kind="task" :progress="progress" />
        <div v-if="hasResult || status === 'error'" class="insight-runtime-state">
          <div class="insight-runtime-state__row">
            <span>{{ stateText }}</span>
            <button v-if="status === 'error'" type="button" class="insight-runtime-retry" @click="retry">重试</button>
          </div>
        </div>
        <template v-if="hasResult">
          <div class="shipment-task-order__head">
            <span class="shipment-task-order__step">3</span>
            <strong class="shipment-task-order__title">出货风险解决任务令</strong>
            <span class="shipment-task-order__sub">责任角色、目标和验收来自当前分析</span>
          </div>
          <div class="shipment-task-order__summary" :title="summary">{{ summary }}</div>
          <div v-if="!openRecommendations.length" class="insight-runtime-empty">尚无经过证据校验的措施，需先核实原因与责任口径。</div>
          <article v-for="(item, index) in openRecommendations" :key="item.id" class="shipment-task-order__task">
            <div class="shipment-task-order__task-head">
              <span class="shipment-task-order__no">{{ index + 1 }}</span>
              <strong class="shipment-task-order__task-title">{{ item.action }}</strong>
              <span class="shipment-task-order__deadline">{{ deadlineText(item) }}</span>
            </div>
            <div class="shipment-task-order__meta">
              <span class="shipment-task-order__owner">{{ item.ownerRole || '责任角色未提供' }}</span>
              <span class="shipment-task-order__acceptance">验收：{{ item.acceptance }}</span>
              <button v-if="hasRecommendationDetail(item)" type="button" class="shipment-task-order__detail-toggle"
                      :aria-expanded="String(isRecommendationExpanded(item.id))"
                      @click="toggleRecommendationDetail(item.id)">
                {{ isRecommendationExpanded(item.id) ? '收起' : '查看详情' }}
              </button>
            </div>
            <div v-if="isRecommendationExpanded(item.id)" class="shipment-task-order__detail">
              <div v-if="linkedCauseTitles(item)"><span class="shipment-task-order__label">关联原因：</span>{{ linkedCauseTitles(item) }}</div>
              <div>{{ recommendationDetail(item) }}</div>
            </div>
          </article>
          <div class="shipment-task-order__foot">
            <span class="shipment-task-order__hint">依据 {{ evidenceCount }} 条证据生成，限制：{{ limitations[0] || '未提供' }}</span>
          </div>
          <div class="shipment-task-order__actions">
            <span v-if="task" class="shipment-task-order__issued">{{ taskStatus }} · {{ task.id }}</span>
            <span v-if="taskNotice" class="shipment-task-order__notice" role="status">{{ taskNotice }}</span>
            <span v-if="taskError" class="shipment-task-order__error" role="alert">{{ taskError }}</span>
            <button v-if="!dispatched" type="button" class="shipment-task-order__primary"
                    :disabled="Boolean(busy) || !canCreate" @click="task ? openEditor() : generateDraft()">
              {{ busy === 'draft' ? '正在生成草稿…' : task ? '编辑任务令' : '生成任务令草稿' }}
            </button>
            <span v-else class="shipment-task-order__hint">待办已调用服务端下发，接收人不在页面中传递</span>
          </div>
          <details v-if="receipts.length" class="shipment-task-order__receipts">
            <summary>查看下发回执</summary>
            <div v-for="(receipt, index) in receipts" :key="index">
              {{ index + 1 }}. {{ receipt.message || receipt.status || '已提交' }}
            </div>
          </details>
        </template>

        <div v-if="dialogOpen" class="shipment-task-order__modal" role="dialog" aria-modal="true" aria-label="任务令草稿">
          <div class="shipment-task-order__dialog">
            <div class="shipment-task-order__dialog-head">
              <div>
                <strong>任务令草稿</strong>
                <span v-if="task" class="shipment-task-order__hint"> · {{ taskStatus }}</span>
              </div>
              <button type="button" class="shipment-task-order__close" :disabled="Boolean(busy)" @click="closeDialog">×</button>
            </div>
            <div v-if="task" class="shipment-task-order__form">
              <label>标题<input v-model="task.title" maxlength="180" :disabled="Boolean(busy)"></label>
              <label>目标<textarea v-model="task.goal" rows="3" maxlength="2000" :disabled="Boolean(busy)"></textarea></label>
              <div v-for="(measure, index) in task.measures" :key="measure.id" class="shipment-task-order__measure">
                <strong>措施 {{ index + 1 }}</strong>
                <div class="shipment-task-order__measure-grid">
                  <label class="shipment-task-order__measure-wide">措施内容<input v-model="measure.action" maxlength="1000" :disabled="Boolean(busy)"></label>
                  <label>责任角色<input v-model="measure.owner" maxlength="100" :disabled="Boolean(busy)"></label>
                  <label>期限<input v-model="measure.deadline" maxlength="120" :disabled="Boolean(busy)"></label>
                  <label class="shipment-task-order__measure-wide">验收标准<textarea v-model="measure.acceptance" rows="2" maxlength="600" :disabled="Boolean(busy)"></textarea></label>
                </div>
              </div>
            </div>
            <div v-if="taskError" class="shipment-task-order__error" role="alert">{{ taskError }}</div>
            <div v-if="taskNotice" class="shipment-task-order__notice" role="status">{{ taskNotice }}</div>
            <div class="shipment-task-order__dialog-foot">
              <span class="shipment-task-order__hint">接收人由服务端安全映射，页面不传手机号</span>
              <button type="button" class="shipment-task-order__secondary" :disabled="Boolean(busy)" @click="closeDialog">取消</button>
              <button type="button" class="shipment-task-order__secondary" :disabled="Boolean(busy)" @click="saveDraft">
                {{ busy === 'save' ? '保存中…' : '保存草稿' }}
              </button>
              <button type="button" class="shipment-task-order__primary" :disabled="Boolean(busy)" @click="dispatchDraft">
                {{ busy === 'dispatch' ? '下发中…' : '确认下发待办' }}
              </button>
            </div>
          </div>
        </div>
      </section>
    `,
  })
)
