// 根因深度分析: the root-cause row opens the real analysis Workbench in an
// embedded two-pane frame (left conversation, right dashboard) instead of a
// second chat UI.  The cockpit stores the clause through
// /api/analysis360/handoff, then loads /workbench in root-cause embed mode:
// prefill only (send=0), manual send, isolated 360 session.
const STYLE_ID = 'deep-analysis-dialog-style'

const CSS = `
.deep-analysis-workbench-backdrop{position:fixed;inset:0;z-index:1200;display:flex;align-items:stretch;justify-content:center;padding:12px;background:rgba(0,0,0,.45)}
.deep-analysis-workbench{display:flex;flex-direction:column;width:min(1680px,100%);height:100%;border-radius:10px;background:var(--cockpit-surface,#fff);color:var(--cockpit-text,#1f2329);box-shadow:0 12px 32px rgba(0,0,0,.24);overflow:hidden}
.deep-analysis-workbench__context{display:flex;align-items:flex-start;gap:12px;padding:10px 16px;border-bottom:1px solid var(--cockpit-divider,#e5e6eb);background:var(--cockpit-surface-2,#f7f8fa)}
.deep-analysis-workbench__context-main{min-width:0;flex:1;display:flex;flex-direction:column;gap:2px}
.deep-analysis-workbench__title{margin:0;font-size:14px;line-height:22px}
.deep-analysis-workbench__name{font-size:13px;line-height:20px;font-weight:600}
.deep-analysis-workbench__desc{margin:0;color:var(--cockpit-text-secondary,#4e5969);font-size:12px;line-height:19px;overflow-wrap:anywhere;white-space:pre-line;max-height:38px;overflow:auto}
.deep-analysis-workbench__meta{color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:18px}
.deep-analysis-workbench__close{flex:none;width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:var(--cockpit-text-help,#8f959e);font-size:20px;line-height:26px;cursor:pointer}
.deep-analysis-workbench__close:hover{background:var(--cockpit-primary-10,#e8f3ff)}
.deep-analysis-workbench__body{position:relative;flex:1;min-height:0;background:var(--cockpit-surface,#fff)}
.deep-analysis-workbench__frame{display:block;width:100%;height:100%;border:0}
.deep-analysis-workbench__state{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;padding:24px;color:var(--cockpit-text-secondary,#4e5969);font-size:13px;line-height:22px;text-align:center}
.deep-analysis-workbench__state--error{color:var(--cockpit-error,#f53f3f);background:var(--cockpit-error-bg,#fff1f0)}
`

function ensureStyle() {
  if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = CSS
  if (document.head && typeof document.head.appendChild === 'function') document.head.appendChild(style)
}

async function readDetail(response) {
  try {
    const body = await response.json()
    return body?.detail || body?.message || ''
  } catch (_) {
    return ''
  }
}

export const DeepAnalysisDialog = window.Vue.defineComponent({
  name: 'DeepAnalysisDialog',
  props: {
    open: {type: Boolean, default: false},
    // Built by the card with deepAnalysisPayload('cause', …): the clause, the
    // card metadata, the sibling causes and the item's evidence facts.
    payload: {type: Object, default: null},
    item: {type: Object, default: null},
    // Application root (the origin path serving /workbench and /api/*).
    root: {type: String, default: ''},
  },
  emits: ['close'],
  setup(props, {emit}) {
    const {ref, computed, watch, onBeforeUnmount} = window.Vue
    ensureStyle()
    const src = ref('')
    const loading = ref(false)
    const error = ref('')
    const panel = ref(null)
    const frame = ref(null)
    let controller = null
    let disposed = false
    let opener = null

    const itemTitle = computed(() => String(props.item?.title || props.item?.causeCode || '根因'))
    const metaLine = computed(() => {
      const parts = [props.item?.stageLabel, props.payload?.period, props.payload?.measurementDate].filter(Boolean)
      return parts.join(' · ')
    })

    function abort() {
      if (controller) {
        try { controller.abort() } catch (_) { /* already closed */ }
        controller = null
      }
    }

    function reset() {
      src.value = ''
      error.value = ''
      loading.value = false
      disposed = false
      abort()
      opener = document.activeElement || null
    }

    async function start() {
      loading.value = true
      controller = new AbortController()
      try {
        const response = await window.fetch(`${props.root}/api/analysis360/handoff`, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(props.payload || {}), signal: controller.signal,
        })
        if (!response.ok) throw new Error((await readDetail(response)) || `深度分析暂不可用（${response.status}）`)
        const {id} = await response.json()
        if (disposed) return
        src.value = `${props.root}/workbench?embed=rootcause&a360=${encodeURIComponent(id)}&send=0`
      } catch (failure) {
        if (disposed || failure?.name === 'AbortError') return
        error.value = failure?.message || '深度分析暂不可用'
      } finally {
        if (!disposed) loading.value = false
      }
    }

    function close() {
      disposed = true
      abort()
      const target = opener
      opener = null
      emit('close')
      if (target && typeof target.focus === 'function') {
        try { target.focus() } catch (_) { /* element gone */ }
      }
    }

    function focusFrame() {
      // Same-origin frame: put the caret in the workbench composer so the
      // user can edit the prefilled root-cause question straight away.
      const node = frame.value
      const doc = node && node.contentDocument
      const input = doc && typeof doc.getElementById === 'function' ? doc.getElementById('chat-input') : null
      if (input && typeof input.focus === 'function') {
        try { input.focus() } catch (_) { /* frame not ready */ }
      }
    }

    function onKeydown(event) {
      if (!event || event.key !== 'Escape') return
      event.preventDefault?.()
      close()
    }

    watch(() => props.open, open => {
      if (!open) {
        disposed = true
        abort()
        return
      }
      reset()
      start()
    }, {immediate: true})

    onBeforeUnmount(() => {
      disposed = true
      abort()
    })

    return {src, loading, error, panel, frame, itemTitle, metaLine, close, onKeydown, focusFrame}
  },
  template: `
    <teleport to="body">
      <div v-if="open" class="deep-analysis-workbench-backdrop" @click.self="close">
        <section ref="panel" class="deep-analysis-workbench" role="dialog" aria-modal="true"
                 aria-labelledby="deep-analysis-workbench-title" @keydown="onKeydown">
          <header class="deep-analysis-workbench__context">
            <div class="deep-analysis-workbench__context-main">
              <h2 id="deep-analysis-workbench-title" class="deep-analysis-workbench__title">深度分析 · 根因</h2>
              <span class="deep-analysis-workbench__name">{{ itemTitle }}</span>
              <p v-if="item?.description" class="deep-analysis-workbench__desc">{{ item.description }}</p>
              <span class="deep-analysis-workbench__meta">{{ metaLine }}</span>
            </div>
            <button type="button" class="deep-analysis-workbench__close" aria-label="关闭深度分析" @click="close">×</button>
          </header>
          <div class="deep-analysis-workbench__body">
            <div v-if="error" class="deep-analysis-workbench__state deep-analysis-workbench__state--error" role="alert">
              {{ error }}
            </div>
            <div v-else-if="loading || !src" class="deep-analysis-workbench__state">正在准备分析工作区…</div>
            <iframe v-if="src && !error" ref="frame" class="deep-analysis-workbench__frame" :src="src"
                    title="根因深度分析工作区" referrerpolicy="same-origin" @load="focusFrame"></iframe>
          </div>
        </section>
      </div>
    </teleport>
  `,
})
