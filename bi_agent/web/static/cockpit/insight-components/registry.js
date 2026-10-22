window.InsightComponents = window.InsightComponents || {}

export function registerInsightComponent(id, component) {
  window.InsightComponents[id] = component
}

export function loadInsightStyle(metaUrl) {
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = new URL('./index.css', metaUrl).href
  document.head.appendChild(link)
}
