import {markdownLite, promptFor, reduceStream, splitSSEFrames} from './model.js'

// 深度分析 dialog: each root-cause row of a cockpit card opens this modal and
// talks to the 360 智能分析 agent in place.  The clause still travels through
// /api/analysis360/handoff (the agent re-anchors it in the 流程360全局本体), and
// the answer streams back into the dialog instead of a separate workbench tab.

const STYLE_ID = 'deep-analysis-dialog-style'

const CSS = `
.deep-analysis-dialog-backdrop{position:fixed;inset:0;z-index:1200;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(0,0,0,.45)}
.deep-analysis-dialog{display:flex;flex-direction:column;width:min(760px,100%);max-height:calc(100vh - 48px);border-radius:10px;background:var(--cockpit-surface,#fff);color:var(--cockpit-text,#1f2329);box-shadow:0 12px 32px rgba(0,0,0,.24);overflow:hidden}
.deep-analysis-dialog__head{display:flex;align-items:flex-start;gap:12px;padding:16px 20px 12px;border-bottom:1px solid var(--cockpit-divider,#e5e6eb)}
.deep-analysis-dialog__title{margin:0;font-size:16px;line-height:24px}
.deep-analysis-dialog__clause{margin:2px 0 0;color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:20px;overflow-wrap:anywhere}
.deep-analysis-dialog__close{margin-left:auto;flex:none;width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:var(--cockpit-text-help,#8f959e);font-size:20px;line-height:26px;cursor:pointer}
.deep-analysis-dialog__close:hover{background:var(--cockpit-primary-10,#e8f3ff)}
.deep-analysis-dialog__context{display:flex;flex-direction:column;gap:4px;padding:12px 20px;border-bottom:1px solid var(--cockpit-divider,#e5e6eb);background:var(--cockpit-surface-2,#f7f8fa)}
.deep-analysis-dialog__tag{align-self:flex-start;padding:0 8px;border-radius:10px;background:var(--cockpit-warning-bg,#fff7e8);color:var(--cockpit-warning,#d97706);font-size:12px;line-height:20px}
.deep-analysis-dialog__context b{font-size:13px;line-height:22px}
.deep-analysis-dialog__desc{margin:0;font-size:12px;line-height:20px;color:var(--cockpit-text-secondary,#4e5969);overflow-wrap:anywhere;white-space:pre-line}
.deep-analysis-dialog__meta{color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:20px}
.deep-analysis-dialog__body{flex:1;min-height:120px;padding:16px 20px;overflow:auto}
.deep-analysis-dialog__hint{margin:0;color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:20px}
.deep-analysis-dialog__turn{display:flex;margin-bottom:10px}
.deep-analysis-dialog__turn--user{justify-content:flex-end}
.deep-analysis-dialog__bubble{max-width:88%;padding:10px 14px;border-radius:8px;font-size:13px;line-height:22px;overflow-wrap:anywhere;user-select:text}
.deep-analysis-dialog__turn--user .deep-analysis-dialog__bubble{background:var(--cockpit-primary-10,#e8f3ff);color:var(--cockpit-text,#1f2329)}
.deep-analysis-dialog__turn--assistant .deep-analysis-dialog__bubble{width:100%;background:transparent;padding:0}
.deep-analysis-dialog__bubble p{margin:0 0 8px}
.deep-analysis-dialog__bubble h4{margin:12px 0 6px;font-size:13px;line-height:22px}
.deep-analysis-dialog__bubble ul,.deep-analysis-dialog__bubble ol{margin:0 0 8px;padding-left:20px}
.deep-analysis-dialog__bubble code{padding:0 4px;border-radius:4px;background:var(--cockpit-surface-2,#f7f8fa);font-size:12px}
.deep-analysis-dialog__activity{margin-top:4px;color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:20px}
.deep-analysis-dialog__error{margin:8px 0;padding:8px 10px;border-radius:6px;background:var(--cockpit-error-bg,#fff1f0);color:var(--cockpit-error,#f53f3f);font-size:12px;line-height:20px;overflow-wrap:anywhere}
.deep-analysis-dialog__choices{margin-top:10px;padding:10px 12px;border:1px solid var(--cockpit-divider,#e5e6eb);border-radius:8px}
.deep-analysis-dialog__choices p{margin:0 0 8px;font-size:13px;line-height:22px}
.deep-analysis-dialog__choice-list{display:flex;flex-wrap:wrap;gap:8px}
.deep-analysis-dialog__choice{padding:0 12px;height:28px;line-height:26px;border:1px solid var(--cockpit-primary,#165dff);border-radius:14px;background:transparent;color:var(--cockpit-primary,#165dff);font-size:12px;cursor:pointer}
.deep-analysis-dialog__choice:hover:not(:disabled){background:var(--cockpit-primary,#165dff);color:#fff}
.deep-analysis-dialog__foot{padding:12px 20px 16px;border-top:1px solid var(--cockpit-divider,#e5e6eb)}
.deep-analysis-dialog__composer{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid var(--cockpit-input-border,#c9cdd4);border-radius:6px;background:var(--cockpit-surface,#fff);color:inherit;font:inherit;font-size:13px;line-height:22px;resize:vertical}
.deep-analysis-dialog__composer:focus{outline:2px solid var(--cockpit-primary-40,#94bfff);outline-offset:-1px}
.deep-analysis-dialog__actions{display:flex;align-items:center;gap:12px;margin-top:8px}
.deep-analysis-dialog__notice{flex:1;color:var(--cockpit-text-help,#8f959e);font-size:12px;line-height:20px}
.deep-analysis-dialog__send{flex:none;padding:0 16px;height:30px;border:0;border-radius:6px;background:var(--cockpit-primary,#165dff);color:#fff;font-size:13px;cursor:pointer}
.deep-analysis-dialog__send:disabled{opacity:.5;cursor:default}
@media (prefers-reduced-motion:reduce){.deep-analysis-dialog__bubble{scroll-behavior:auto}}
`

function ensureStyle() {
  if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = CSS
  document.head.appendChild(style)
}

let sessionSequence = 0

function newSessionId() {
  try {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') return window.crypto.randomUUID()
  } catch (_) { /* insecure context */ }
  sessionSequence += 1
  return `deep-analysis-${Date.now()}-${sessionSequence}`
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
    // Application root (the origin path serving /api/analysis360/*).
    root: {type: String, default: ''},
  },
  emits: ['close'],
  setup(props, {emit}) {
    const {ref, computed, nextTick, watch} = window.Vue
    ensureStyle()
    const prompt = ref('')
    const turns = ref([])
    const live = ref(null)
    const busy = ref(false)
    const error = ref('')
    const choices = ref(null)
    const body = ref(null)
    const composer = ref(null)
    let controller = null
    let sessionId = newSessionId()
    let handoffId = ''

    const itemTitle = computed(() => String(props.item?.title || props.item?.causeCode || '根因'))
    const metaLine = computed(() => {
      const clause = props.payload?.clause || {}
      const parts = [clause.code, props.payload?.period, props.payload?.measurementDate]
      return parts.filter(Boolean).join(' · ')
    })

    function reset() {
      prompt.value = promptFor(props.item)
      turns.value = []
      live.value = null
      busy.value = false
      error.value = ''
      choices.value = null
      sessionId = newSessionId()
      handoffId = ''
    }

    function close() {
      if (controller) {
        try { controller.abort() } catch (_) { /* already closed */ }
        controller = null
      }
      emit('close')
    }

    function push(userText) {
      turns.value = [...turns.value, {role: 'user', text: userText}]
      live.value = {text: '', activity: ''}
      if (body.value) body.value.scrollTop = body.value.scrollHeight
    }

    function settle() {
      if (live.value && live.value.text.trim()) {
        turns.value = [...turns.value, {role: 'assistant', text: live.value.text}]
      }
      live.value = null
      busy.value = false
    }

    async function ensureHandoff() {
      if (handoffId) return handoffId
      const response = await window.fetch(`${props.root}/api/analysis360/handoff`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(props.payload || {}),
      })
      if (!response.ok) throw new Error((await readDetail(response)) || `深度分析暂不可用（${response.status}）`)
      const {id} = await response.json()
      handoffId = id
      return id
    }

    async function stream(path, bodyText) {
      controller = new AbortController()
      const response = await window.fetch(`${props.root}${path}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(bodyText), signal: controller.signal,
      })
      if (!response.ok) throw new Error((await readDetail(response)) || `深度分析暂不可用（${response.status}）`)
      const state = {text: live.value?.text || '', activity: '', busy: true, error: '', choices: null}
      const apply = event => {
        Object.assign(state, reduceStream(state, event))
        live.value = {text: state.text, activity: state.activity}
        if (state.choices) choices.value = state.choices
        if (state.error) error.value = state.error
        if (state.busy === false) busy.value = false
        if (body.value) body.value.scrollTop = body.value.scrollHeight
      }
      if (!response.body) {
        apply({type: 'text', text: await response.text()})
        apply({type: 'done'})
        return
      }
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const {value, done} = await reader.read()
        if (done) break
        buffer += decoder.decode(value, {stream: true})
        const {events, rest} = splitSSEFrames(buffer)
        buffer = rest
        for (const event of events) apply(event)
        if (state.busy === false && state.choices) {
          try { await reader.cancel() } catch (_) { /* already closed */ }
          break
        }
      }
      if (buffer.trim()) {
        for (const event of splitSSEFrames(`${buffer}\n\n`).events) apply(event)
      }
    }

    async function send() {
      const text = prompt.value.trim()
      if (!text || busy.value) return
      busy.value = true
      error.value = ''
      choices.value = null
      push(text)
      const bodyText = {message: text, visible_user_text: text, session_id: sessionId}
      // The handoff creates the 360 session; only the first request may carry
      // it, otherwise the server would replace the session and replay the clause.
      const firstTurn = !handoffId
      try {
        if (firstTurn) bodyText.analysis360_handoff = await ensureHandoff()
        await stream('/api/analysis360/chat', bodyText)
        if (firstTurn) handoffId = ''
      } catch (failure) {
        if (failure?.name !== 'AbortError') error.value = failure?.message || '深度分析暂不可用'
      } finally {
        settle()
        composer.value?.focus()
      }
    }

    async function choose(option) {
      if (busy.value || !choices.value) return
      const ids = [String(option?.id ?? option?.label ?? '')].filter(Boolean)
      const labels = [String(option?.label ?? option?.id ?? '')].filter(Boolean)
      if (!ids.length) return
      choices.value = null
      error.value = ''
      const text = labels[0] || ids[0]
      settle()
      turns.value = [...turns.value, {role: 'user', text}]
      live.value = {text: '', activity: ''}
      busy.value = true
      try {
        await stream('/api/analysis360/choice',
          {choice_ids: ids, choice_labels: labels, session_id: sessionId})
      } catch (failure) {
        if (failure?.name !== 'AbortError') error.value = failure?.message || '深度分析暂不可用'
      } finally {
        settle()
      }
    }

    watch(() => props.open, open => {
      if (!open) return
      reset()
      nextTick(() => composer.value?.focus())
    }, {immediate: true})

    return {
      prompt, turns, live, busy, error, choices, body, composer, itemTitle, metaLine,
      send, choose, close,
      rendered: text => markdownLite(text),
    }
  },
  template: `
    <div v-if="open" class="deep-analysis-dialog-backdrop" @click.self="close">
      <section class="deep-analysis-dialog" role="dialog" aria-modal="true" aria-labelledby="deep-analysis-dialog-title">
        <header class="deep-analysis-dialog__head">
          <div>
            <h2 id="deep-analysis-dialog-title" class="deep-analysis-dialog__title">深度分析 · 根因</h2>
            <p class="deep-analysis-dialog__clause">{{ metaLine || '360 智能分析 · 流程360全局本体' }}</p>
          </div>
          <button type="button" class="deep-analysis-dialog__close" aria-label="关闭深度分析" @click="close">×</button>
        </header>
        <div class="deep-analysis-dialog__context">
          <span class="deep-analysis-dialog__tag">根因</span>
          <b>{{ itemTitle }}</b>
          <p v-if="item?.description" class="deep-analysis-dialog__desc">{{ item.description }}</p>
          <span class="deep-analysis-dialog__meta">{{ item?.stageLabel || '' }}</span>
        </div>
        <div ref="body" class="deep-analysis-dialog__body" aria-live="polite">
          <p v-if="!turns.length && !live" class="deep-analysis-dialog__hint">
            点击「开始深度分析」后，360 智能分析会先在全局本体中定位这条根因，再按你的选择下钻取证。
          </p>
          <div v-for="(turn, index) in turns" :key="index" class="deep-analysis-dialog__turn" :class="'deep-analysis-dialog__turn--' + turn.role">
            <div v-if="turn.role === 'assistant'" class="deep-analysis-dialog__bubble" v-html="rendered(turn.text)"></div>
            <div v-else class="deep-analysis-dialog__bubble">{{ turn.text }}</div>
          </div>
          <div v-if="live" class="deep-analysis-dialog__turn deep-analysis-dialog__turn--assistant">
            <div class="deep-analysis-dialog__bubble" v-html="rendered(live.text)"></div>
            <div v-if="live.activity" class="deep-analysis-dialog__activity">{{ live.activity }}</div>
          </div>
          <div v-if="error" class="deep-analysis-dialog__error" role="alert">{{ error }}</div>
          <div v-if="choices" class="deep-analysis-dialog__choices">
            <p>{{ choices.question }}</p>
            <div class="deep-analysis-dialog__choice-list">
              <button v-for="option in choices.options" :key="option.id || option.label" type="button"
                      class="deep-analysis-dialog__choice" :disabled="busy" @click="choose(option)">
                {{ option.label || option.title || option.id }}
              </button>
            </div>
          </div>
        </div>
        <footer class="deep-analysis-dialog__foot">
          <textarea ref="composer" v-model="prompt" class="deep-analysis-dialog__composer" rows="3"
                    :disabled="busy" aria-label="深度分析提示词"
                    @keydown.enter.exact.prevent="send"></textarea>
          <div class="deep-analysis-dialog__actions">
            <span class="deep-analysis-dialog__notice">只带入这条根因的上下文；分析以流程360全局本体为准。</span>
            <button type="button" class="deep-analysis-dialog__send" :disabled="busy || !prompt.trim()" @click="send">
              {{ busy ? '分析中…' : '开始深度分析' }}
            </button>
          </div>
        </footer>
      </section>
    </div>
  `,
})
