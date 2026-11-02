const {computed} = window.Vue

const ACTION_LABELS = {
  investigation: '核查任务',
  remediation: '处置任务',
  pending: '待确认任务',
}

export const TaskOrderDialog = Vue.defineComponent({
  name: 'TaskOrderDialog',
  props: {
    task: {type: Object, default: null},
    busy: {type: String, default: ''},
    error: {type: String, default: ''},
    notice: {type: String, default: ''},
    receipts: {type: Array, default: () => []},
    taskStatus: {type: String, default: ''},
    dispatched: {type: Boolean, default: false},
  },
  emits: ['close', 'save', 'dispatch'],
  setup(props) {
    const readonly = computed(() => !props.task || props.task.status !== 'draft' || props.dispatched)
    const confirmed = computed(() => (props.task?.measures || []).every(item => (
      item.ownerConfirmed === true && item.deadlineConfirmed === true
    )))
    function typeLabel(value) {
      return ACTION_LABELS[value] || ACTION_LABELS.pending
    }
    return {readonly, confirmed, typeLabel}
  },
  template: `
    <div class="task-order-dialog__backdrop" role="dialog" aria-modal="true" aria-label="任务令草稿">
      <div class="task-order-dialog">
        <div class="task-order-dialog__head">
          <div>
            <strong>任务令草稿</strong>
            <span v-if="task" class="task-order-dialog__status"> · {{ taskStatus }}</span>
          </div>
          <button type="button" class="task-order-dialog__icon" :disabled="Boolean(busy)" aria-label="关闭" @click="$emit('close')">×</button>
        </div>

        <div v-if="task" class="task-order-dialog__body">
          <div class="task-order-dialog__notice task-order-dialog__notice--neutral">
            任务正文由已交付建议生成；浏览器只提交选中的建议编号，不能提交自定义正文。
          </div>
          <label class="task-order-dialog__field">
            <span>标题</span>
            <input v-model="task.title" maxlength="180" :disabled="readonly || Boolean(busy)">
          </label>
          <label class="task-order-dialog__field">
            <span>目标</span>
            <textarea v-model="task.goal" rows="3" maxlength="2000" :disabled="readonly || Boolean(busy)"></textarea>
          </label>

          <article v-for="(measure, index) in task.measures" :key="measure.id" class="task-order-dialog__measure">
            <div class="task-order-dialog__measure-head">
              <strong>措施 {{ index + 1 }}</strong>
              <span class="task-order-dialog__type">{{ typeLabel(measure.actionType) }}</span>
            </div>
            <label class="task-order-dialog__field task-order-dialog__field--wide">
              <span>措施内容</span>
              <input v-model="measure.action" maxlength="1000" :disabled="readonly || Boolean(busy)">
            </label>
            <div class="task-order-dialog__grid">
              <label class="task-order-dialog__field">
                <span>责任角色 <small>建议值，待确认</small></span>
                <input v-model="measure.owner" maxlength="100" :disabled="readonly || Boolean(busy)"
                       @input="measure.ownerConfirmed = false">
              </label>
              <label class="task-order-dialog__field">
                <span>期限 <small>建议值，待确认</small></span>
                <input v-model="measure.deadline" maxlength="120" :disabled="readonly || Boolean(busy)"
                       @input="measure.deadlineConfirmed = false">
              </label>
            </div>
            <label class="task-order-dialog__field task-order-dialog__field--wide">
              <span>验收标准</span>
              <textarea v-model="measure.acceptance" rows="2" maxlength="600" :disabled="readonly || Boolean(busy)"></textarea>
            </label>
            <div class="task-order-dialog__evidence">
              关联证据：{{ (measure.evidenceIds || []).join('、') || '历史草稿未提供' }}
              <template v-if="(measure.causeIds || []).length">；关联原因：{{ measure.causeIds.join('、') }}</template>
            </div>
            <div class="task-order-dialog__confirm">
              <label><input v-model="measure.ownerConfirmed" type="checkbox" :disabled="readonly || Boolean(busy)"> 我已确认责任角色</label>
              <label><input v-model="measure.deadlineConfirmed" type="checkbox" :disabled="readonly || Boolean(busy)"> 我已确认期限</label>
            </div>
          </article>
        </div>

        <div v-if="error" class="task-order-dialog__error" role="alert">{{ error }}</div>
        <div v-if="notice" class="task-order-dialog__notice" role="status">{{ notice }}</div>
        <details v-if="receipts.length" class="task-order-dialog__receipts">
          <summary>查看下发回执</summary>
          <div v-for="(receipt, index) in receipts" :key="index">
            {{ index + 1 }}. {{ receipt.message || receipt.status || '已提交' }}
          </div>
        </details>

        <div class="task-order-dialog__foot">
          <span class="task-order-dialog__hint">接收人由服务端安全映射，页面不传手机号</span>
          <button type="button" class="task-order-dialog__secondary" :disabled="Boolean(busy)" @click="$emit('close')">关闭</button>
          <button v-if="!readonly" type="button" class="task-order-dialog__secondary"
                  :disabled="Boolean(busy) || !confirmed" @click="$emit('save')">
            {{ busy === 'save' ? '保存中…' : '保存草稿' }}
          </button>
          <button v-if="!readonly" type="button" class="task-order-dialog__primary"
                  :disabled="Boolean(busy) || !confirmed" @click="$emit('dispatch')">
            {{ busy === 'dispatch' ? '下发中…' : '确认下发待办' }}
          </button>
        </div>
      </div>
    </div>
  `,
})
