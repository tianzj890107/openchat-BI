// 智能助手: a floating button at the cockpit's bottom-right that opens the
// Ontology Analyst workbench, embedded in this page, in its 360 智能分析 mode
// (…/workbench?a360=assistant).  The workbench keeps its own SOP steps,
// conversation and dashboard; the 360 agent works on 亿纬锂能_流程360全局本体
// following its access strategy, with the database and model from .env.
//
// The frame is created on the first open and kept while the panel is closed,
// so a running conversation is not lost.

export const ASSISTANT_PATH = '/workbench?a360=assistant';

export function assistantUrl(root) {
  return `${String(root || '').replace(/\/+$/, '')}${ASSISTANT_PATH}`;
}

export function mountAssistant(doc = document, win = window) {
  if (!doc.body || doc.getElementById('cockpit-assistant-fab')) return null;
  const meta = doc.querySelector('meta[name="app-root"]');
  const root = meta ? meta.getAttribute('content') || '' : '';
  const url = assistantUrl(root.startsWith('@@') ? '' : root);

  const fab = doc.createElement('button');
  fab.type = 'button';
  fab.id = 'cockpit-assistant-fab';
  fab.className = 'cockpit-assistant-fab';
  fab.setAttribute('aria-haspopup', 'dialog');
  fab.setAttribute('aria-expanded', 'false');
  fab.setAttribute('aria-controls', 'cockpit-assistant-panel');
  fab.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 3c4.97 0 9 3.58 9 8s-4.03 8-9 8c-1.1 0-2.15-.17-3.12-.49L4 20l1.33-3.55C3.87 15.05 3 13.12 3 11c0-4.42 4.03-8 9-8z" fill="currentColor"/><circle cx="8.5" cy="11" r="1.2" fill="#fff"/><circle cx="12" cy="11" r="1.2" fill="#fff"/><circle cx="15.5" cy="11" r="1.2" fill="#fff"/></svg><span>智能助手</span>';

  const panel = doc.createElement('section');
  panel.id = 'cockpit-assistant-panel';
  panel.className = 'cockpit-assistant';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'false');
  panel.setAttribute('aria-label', '智能助手');
  panel.hidden = true;
  panel.innerHTML = `
    <header class="cockpit-assistant__head">
      <div class="cockpit-assistant__title">
        <strong>智能助手</strong>
        <small>Ontology Analyst · 流程360全局本体</small>
      </div>
      <div class="cockpit-assistant__actions">
        <button type="button" class="cockpit-assistant__action" data-action="expand" aria-pressed="false" title="放大">放大</button>
        <a class="cockpit-assistant__action" data-action="window" href="${url}" target="_blank" rel="noopener" title="在新窗口打开">新窗口</a>
        <button type="button" class="cockpit-assistant__action cockpit-assistant__close" data-action="close" aria-label="关闭智能助手" title="关闭">×</button>
      </div>
    </header>
    <div class="cockpit-assistant__body"></div>`;

  const body = panel.querySelector('.cockpit-assistant__body');
  const expand = panel.querySelector('[data-action="expand"]');
  let frame = null;

  function open() {
    if (!frame) {
      frame = doc.createElement('iframe');
      frame.className = 'cockpit-assistant__frame';
      frame.title = '智能助手 · 360 智能分析';
      frame.src = url;
      body.appendChild(frame);
    }
    panel.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    fab.classList.add('is-open');
  }
  function close() {
    panel.hidden = true;
    fab.setAttribute('aria-expanded', 'false');
    fab.classList.remove('is-open');
    fab.focus();
  }
  fab.addEventListener('click', () => (panel.hidden ? open() : close()));
  panel.querySelector('[data-action="close"]').addEventListener('click', close);
  expand.addEventListener('click', () => {
    const wide = !panel.classList.contains('is-wide');
    panel.classList.toggle('is-wide', wide);
    expand.setAttribute('aria-pressed', String(wide));
    expand.textContent = wide ? '还原' : '放大';
    expand.title = wide ? '还原' : '放大';
  });
  doc.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) close();
  });

  doc.body.append(panel, fab);
  return {fab, panel, open, close, url};
}

if (typeof document !== 'undefined' && typeof window !== 'undefined') {
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mountAssistant());
  else mountAssistant();
}
