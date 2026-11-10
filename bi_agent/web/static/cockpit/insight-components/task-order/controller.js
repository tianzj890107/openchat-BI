import {createTaskOrderClient, taskSelectionKey} from './client.js'

const {computed, onMounted, ref} = window.Vue

export const TASK_ACTION_LABELS = {
  investigation: '核查建议',
  remediation: '改善建议',
  pending: '待确认建议',
}

const TASK_STATUS = {
  draft: '草稿待确认',
  issued: '已下发',
  accepted: '已接收',
  review: '待验收',
  closed: '已关闭',
}

const TERMINAL = new Set(['issued', 'accepted', 'review', 'closed'])

let styleLoaded = false
export function ensureTaskOrderStyle() {
  if (styleLoaded || typeof document === 'undefined') return
  styleLoaded = true
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.id = 'cockpit-task-order-style'
  const version = document.querySelector('meta[name="cockpit-version"]')?.content || '1'
  const href = new URL('./index.css', import.meta.url)
  href.searchParams.set('v', version)
  link.href = href.href
  document.head.appendChild(link)
}

export function actionTypeLabel(value) {
  return TASK_ACTION_LABELS[value] || TASK_ACTION_LABELS.pending
}

function copyTask(value) {
  return value ? JSON.parse(JSON.stringify(value)) : null
}

export function createTaskOrderController({analysisId, insight, apiBase, identityId}) {
  const client = createTaskOrderClient({apiBase, identityId})
  const task = ref(null)
  const dialogOpen = ref(false)
  const busy = ref('')
  const taskError = ref('')
  const taskNotice = ref('')
  const receipts = ref([])
  const hydrated = ref(false)

  const openRecommendations = computed(() => insight.openRecommendations.value || [])
  const draftableSelected = computed(() => openRecommendations.value.filter(item => (
    item?.actionType === 'investigation' || item?.actionType === 'remediation'
  )))
  const selectedIds = computed(() => draftableSelected.value.map(item => String(item.id)))
  const currentSelectionKey = computed(() => taskSelectionKey(selectedIds.value))
  const taskSelection = computed(() => taskSelectionKey(task.value?.recommendationIds || []))
  const taskMatchesSelection = computed(() => Boolean(
    task.value && currentSelectionKey.value && currentSelectionKey.value === taskSelection.value
  ))
  const dispatched = computed(() => TERMINAL.has(task.value?.status))
  const taskStatus = computed(() => task.value ? (TASK_STATUS[task.value.status] || task.value.status || '状态未知') : '')
  const canCreate = computed(() => Boolean(
    analysisId.value && draftableSelected.value.length && !busy.value
  ))
  const emptyState = computed(() => {
    if (!openRecommendations.value.length) {
      if (!insight.causes.value.length) return '当前没有可选择的业务建议。'
      if (insight.causes.value.some(item => item?.kind === 'hypothesis' || item?.status === 'hypothesis')) {
        return '当前没有可选择的核查建议。'
      }
      return '当前缺少明确核查对象或必要口径，暂不能生成任务草稿。'
    }
    if (!draftableSelected.value.length) return '当前建议尚未明确为核查或改善动作，暂不能生成任务草稿。'
    return ''
  })
  const recommendationHint = computed(() => {
    if (!draftableSelected.value.length) return ''
    if (draftableSelected.value.every(item => item.actionType === 'investigation')) {
      return '可按所选建议生成核查任务。'
    }
    return ''
  })
  const taskButtonLabel = computed(() => {
    if (busy.value === 'draft') return '正在生成草稿…'
    if (taskMatchesSelection.value && task.value?.status === 'draft') return '编辑任务令'
    if (taskMatchesSelection.value && dispatched.value) return '查看任务回执'
    if (task.value && !taskMatchesSelection.value) return '按当前建议生成草稿'
    return '生成任务令草稿'
  })

  function measurePayload() {
    return (task.value?.measures || []).map(item => ({
      id: String(item.id || ''),
      action: String(item.action || '').trim(),
      owner: String(item.owner || '').trim(),
      deadline: String(item.deadline || '').trim(),
      acceptance: String(item.acceptance || '').trim(),
      ownerConfirmed: item.ownerConfirmed === true,
      deadlineConfirmed: item.deadlineConfirmed === true,
    }))
  }

  async function generateDraft() {
    if (busy.value) return
    if (!analysisId.value) {
      taskError.value = '当前分析尚未生成，不能创建任务令草稿'
      return
    }
    if (!draftableSelected.value.length) {
      taskError.value = emptyState.value || '当前没有选中的建议，不能生成任务令草稿'
      return
    }
    busy.value = 'draft'
    taskError.value = ''
    taskNotice.value = ''
    try {
      const value = await client.draft(analysisId.value, selectedIds.value)
      task.value = copyTask(value)
      receipts.value = []
      if (value.status === 'draft') {
        dialogOpen.value = true
        taskNotice.value = '任务令草稿已生成，请核对类型、责任、期限与验收后下发'
      } else {
        taskNotice.value = `任务令${TASK_STATUS[value.status] || value.status || '已提交'}；接收人由服务端安全映射`
      }
    } catch (cause) {
      taskError.value = `生成草稿失败：${cause.message || cause}`
    } finally {
      busy.value = ''
    }
  }

  function openOrGenerate() {
    if (!analysisId.value) {
      taskError.value = '当前分析尚未生成，不能创建任务令草稿'
      return
    }
    if (!draftableSelected.value.length) {
      generateDraft()
      return
    }
    if (taskMatchesSelection.value && task.value) {
      taskError.value = ''
      dialogOpen.value = true
      return
    }
    generateDraft()
  }

  function closeDialog() {
    if (!busy.value) dialogOpen.value = false
  }

  async function persistDraft() {
    if (!task.value || task.value.status !== 'draft') throw new Error('只有草稿状态可以编辑')
    const measures = measurePayload()
    if (!String(task.value.title || '').trim() || !String(task.value.goal || '').trim() || !measures.length) {
      throw new Error('请补齐标题、目标和至少一项措施')
    }
    if (measures.some(item => !item.action || !item.owner || !item.deadline || !item.acceptance)) {
      throw new Error('每项措施都需要填写动作、责任角色、期限和验收标准')
    }
    if (measures.some(item => !item.ownerConfirmed || !item.deadlineConfirmed)) {
      throw new Error('请逐项确认责任角色和建议期限后再保存')
    }
    const saved = await client.save(task.value.id, task.value.revision, {
      title: String(task.value.title).trim(), goal: String(task.value.goal).trim(), measures,
    })
    task.value = copyTask(saved)
    return saved
  }

  async function saveDraft() {
    if (busy.value) return
    busy.value = 'save'
    taskError.value = ''
    taskNotice.value = ''
    try {
      await persistDraft()
      taskNotice.value = '任务令草稿已保存，责任角色与期限已确认'
    } catch (cause) {
      taskError.value = `保存草稿失败：${cause.message || cause}`
    } finally {
      busy.value = ''
    }
  }

  async function dispatchDraft() {
    if (busy.value || dispatched.value) return
    busy.value = 'dispatch'
    taskError.value = ''
    taskNotice.value = ''
    try {
      await persistDraft()
      const result = await client.dispatch(task.value.id)
      receipts.value = result.results || []
      if (result.task) task.value = copyTask(result.task)
      if (!result.accepted) {
        throw new Error(result.message || `仅 ${result.acceptedCount || 0}/${result.total || 0} 项成功`)
      }
      dialogOpen.value = false
      taskNotice.value = `${result.message || '任务令已下发'}；接收人由服务端安全映射`
    } catch (cause) {
      taskError.value = `下发失败：${cause.message || cause}`
    } finally {
      busy.value = ''
    }
  }

  async function hydrate() {
    if (!analysisId.value) return
    try {
      const tasks = await client.listTasks()
      const found = (tasks || []).find(item => String(item.analysisId || '') === analysisId.value
        && taskSelectionKey(item.recommendationIds || []) === currentSelectionKey.value)
      if (found && !task.value) task.value = copyTask(found)
    } catch (_) {
      // Reading an existing draft is an enhancement; generation still works if it fails.
    } finally {
      hydrated.value = true
    }
  }

  onMounted(hydrate)

  return {
    task,
    dialogOpen,
    busy,
    taskError,
    taskNotice,
    receipts,
    taskStatus,
    dispatched,
    canCreate,
    selectedIds,
    taskMatchesSelection,
    emptyState,
    recommendationHint,
    taskButtonLabel,
    actionTypeLabel,
    openOrGenerate,
    generateDraft,
    closeDialog,
    saveDraft,
    dispatchDraft,
  }
}
