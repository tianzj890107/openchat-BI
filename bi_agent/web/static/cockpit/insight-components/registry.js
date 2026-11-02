window.InsightComponents = window.InsightComponents || {}

const stateStyle = document.createElement('style')
stateStyle.id = 'insight-runtime-style'
stateStyle.textContent = `
.insight-runtime-state {
  margin: 0 0 8px;
  color: var(--cockpit-text-help);
  font-size: 12px;
  line-height: 20px;
}
.insight-runtime-state__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.insight-runtime-retry {
  flex: none;
  padding: 0 8px;
  border: 1px solid var(--cockpit-input-border);
  border-radius: 10px;
  background: var(--cockpit-surface);
  color: var(--cockpit-primary);
  font-size: 12px;
  line-height: 20px;
  cursor: pointer;
}
.insight-loading { padding:16px 18px; min-height:100px; border:1px solid var(--cockpit-divider); border-radius:8px; background:linear-gradient(110deg,var(--cockpit-primary-10),var(--cockpit-primary-10)); }
.insight-loading__head { display:flex; align-items:center; gap:8px; margin-bottom:16px; color:var(--cockpit-text-secondary); font-size:13px; }
.insight-loading__spark { color:var(--cockpit-text-help); font-size:19px; }
.insight-loading__dots { margin-left:auto; letter-spacing:3px; }
.insight-loading__line { height:10px; margin:10px 0; border-radius:4px; background:linear-gradient(90deg,var(--cockpit-primary-10) 25%,var(--cockpit-primary-10) 50%,var(--cockpit-primary-10) 75%); background-size:200% 100%; animation:insight-loading-shimmer 1.5s ease-in-out infinite; }
.insight-loading__line--short { width:64%; }
.insight-loading__panel { margin:20px 0; padding:12px; border:1px solid var(--cockpit-divider); border-radius:6px; }
@keyframes insight-loading-shimmer { to { background-position:-200% 0; } }
@media (prefers-reduced-motion:reduce) { .insight-loading__line { animation:none; } }
.insight-runtime-empty {
  color: var(--cockpit-text-help);
  font-size: 12px;
}
.ai-table-state {
  margin: 0 0 8px;
  color: var(--cockpit-text-help);
  font-size: 12px;
  line-height: 20px;
}
.ai-table-state--error {
  color: var(--cockpit-error);
}
`
if (!document.getElementById(stateStyle.id)) document.head.appendChild(stateStyle)

export function registerInsightComponent(id, component) {
  window.InsightComponents[id] = component
}

export function loadInsightStyle(metaUrl) {
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  const version = document.querySelector('meta[name="cockpit-version"]')?.content || '1'
  const href = new URL('./index.css', metaUrl)
  href.searchParams.set('v', version)
  link.href = href.href
  document.head.appendChild(link)
}
