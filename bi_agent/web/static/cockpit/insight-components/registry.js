window.InsightComponents = window.InsightComponents || {}

const stateStyle = document.createElement('style')
stateStyle.id = 'insight-runtime-style'
stateStyle.textContent = `
.insight-runtime-state {
  margin: 0 0 8px;
  color: #8c8c8c;
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
  border: 1px solid #d9d9d9;
  border-radius: 10px;
  background: #fff;
  color: #1677ff;
  font-size: 12px;
  line-height: 20px;
  cursor: pointer;
}
.insight-runtime-empty {
  color: #8c8c8c;
  font-size: 12px;
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
