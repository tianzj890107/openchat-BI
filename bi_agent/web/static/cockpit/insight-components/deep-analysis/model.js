// Pure helpers behind the cockpit 深度分析 dialog.
//
// The dialog talks to the 360 智能分析 agent: the card's cause clause is stored
// by /api/analysis360/handoff and the first chat turn of a fresh session is
// built from that clause.  Everything here is framework free so it can be unit
// tested by tests/deep_analysis_dialog.test.mjs without a browser.

/** Visible prompt typed into the dialog when it opens: 深度分析「<根因>」根因. */
export function promptFor(item) {
  const name = String(item?.title || item?.name || item?.causeCode || item?.code || '').trim()
  return name ? `深度分析「${name}」根因` : '深度分析这条根因'
}

/**
 * Split a growing SSE buffer into complete `data:` frames.
 * Returns the parsed events plus the trailing partial frame to keep buffering.
 */
export function splitSSEFrames(buffer) {
  // Browsers may deliver CRLF frames; both separators must end an event.
  const frames = String(buffer ?? '').replace(/\r\n/g, '\n').split('\n\n')
  const rest = frames.pop() ?? ''
  const events = []
  for (const frame of frames) {
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data:')) continue
      const payload = line.slice(5).trim()
      if (!payload) continue
      try {
        events.push(JSON.parse(payload))
      } catch (_) {
        // A truncated or non-JSON heartbeat is not an event.
      }
    }
  }
  return {events, rest}
}

/** Fold one backend stream event into the dialog's answer state. */
export function reduceStream(state, event) {
  const next = {...state}
  if (!event || typeof event.type !== 'string') return next
  switch (event.type) {
    case 'text_delta':
      next.text = `${next.text || ''}${event.text == null ? '' : String(event.text)}`
      break
    case 'text':
      if (!next.text && event.text) next.text = String(event.text)
      break
    case 'tool_use':
      next.activity = `正在调用 ${event.name || '分析工具'}…`
      break
    case 'tool_result':
      next.activity = ''
      break
    case 'user_choice_requested':
      next.choices = {
        question: event.question || '请选择下一步',
        options: Array.isArray(event.options) ? event.options : [],
      }
      next.busy = false
      break
    case 'awaiting_user_choice':
      next.busy = false
      break
    case 'done':
      next.busy = false
      break
    case 'error':
      next.error = String(event.message || '深度分析暂不可用')
      next.busy = false
      break
    case 'session_superseded':
      next.error = '本次深度分析已被新的请求替换，请重新点击“深度分析”'
      next.busy = false
      break
    case 'stream_interrupted':
      next.error = next.error || String(event.message || '生成中断，内容可能不完整')
      next.busy = false
      break
    default:
      break
  }
  return next
}

const ESCAPES = {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}

function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ESCAPES[char])
}

function inline(text) {
  return escapeHTML(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

/**
 * Render the agent's markdown answer as a small, escaped HTML subset.
 * Only headings, bullet / numbered lists, bold and inline code are honoured;
 * every other character is escaped, so model output can never inject markup.
 */
export function markdownLite(text) {
  const lines = String(text ?? '').split(/\r?\n/)
  const out = []
  let list = ''
  const closeList = () => {
    if (list) {
      out.push(`</${list}>`)
      list = ''
    }
  }
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) {
      closeList()
      continue
    }
    const heading = line.match(/^\s*#{1,4}\s+(.*)$/)
    if (heading) {
      closeList()
      out.push(`<h4>${inline(heading[1])}</h4>`)
      continue
    }
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) {
      if (list !== 'ul') {
        closeList()
        out.push('<ul>')
        list = 'ul'
      }
      out.push(`<li>${inline(bullet[1])}</li>`)
      continue
    }
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    if (numbered) {
      if (list !== 'ol') {
        closeList()
        out.push('<ol>')
        list = 'ol'
      }
      out.push(`<li>${inline(numbered[1])}</li>`)
      continue
    }
    closeList()
    out.push(`<p>${inline(line)}</p>`)
  }
  closeList()
  return out.join('')
}


/** True for a bare Enter; Shift+Enter and IME composition keep the newline. */
export function isSendKey(event) {
  if (!event || event.key !== 'Enter') return false
  if (event.shiftKey) return false
  if (event.isComposing || event.keyCode === 229 || event.which === 229) return false
  return true
}
