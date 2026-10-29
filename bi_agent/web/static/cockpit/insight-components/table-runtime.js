/** Shared ProDataTable adapter for AP fact tables with validated AI columns. */
const { cockpitApiBase, cockpitIdentityId } = window.InsightRuntime

function apQuery(ctx, fields) {
  const dimensions = []
  const indicators = []
  for (const field of fields) {
    const item = {alias: field.label || field.name, identifierCode: field.identifierCode}
    if (field.fieldType === 'Dimension') dimensions.push(item)
    else indicators.push({...item, valueConfig: {numericScale: 2}})
  }
  const pageNum = Number(ctx?.params?.pageNum) > 0 ? Number(ctx.params.pageNum) : 1
  const pageSize = Number(ctx?.params?.pageSize) > 0 ? Number(ctx.params.pageSize) : 10
  const commonConfig = {pagination: {pageNum, pageSize}}
  if (ctx?.filters?.length) commonConfig.filters = {logic: 'AND', children: ctx.filters}
  return {analysisConfig: {dimensions, indicators}, commonConfig}
}

async function requestRows(tableKey, fields, props, ctx) {
  const slot = props.slotProps || {}
  const apiBase = String(slot.apiBase || cockpitApiBase()).replace(/\/$/, '')
  const identityId = Number(slot.identityId) === 2 ? 2 : Number(slot.identityId) === 1 ? 1 : cockpitIdentityId()
  const response = await fetch(`${apiBase}/ai-tables/${encodeURIComponent(tableKey)}/query`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', Accept: 'application/json'},
    body: JSON.stringify({id: identityId, ...apQuery(ctx, fields)}),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload) throw new Error(payload?.detail || `表格查询失败 ${response.status}`)
  return {data: Array.isArray(payload.rows) ? payload.rows : [], total: Number(payload.total) || 0}
}

export function createTableInsight({id, name, title, tableKey, fields, columns, showTitle = false}) {
  const { registerInsightComponent, insightProps } = window.InsightRuntime
  const displayFields = columns.map(column => ({
    fieldType: column.fieldType,
    identifierCode: column.code,
    isTree: Boolean(column.isTree),
    label: column.label,
    valueType: column.valueType,
  }))
  registerInsightComponent(id, Vue.defineComponent({
    name,
    props: insightProps,
    setup(props) {
      const component = Vue.markRaw({
        id: `insight-${id}`,
        type: 'table',
        title,
        showHeader: showTitle,
        showTitle,
        styleConfig: {showCurrentInfo: false},
        dataConfig: {pageSize: 10, sourceType: 'ap', tableFields: displayFields},
        tableColumnConfig: columns,
      })
      const revision = Vue.computed(() => `${props.analysis?.id || ''}:${props.analysis?.updatedAt || ''}`)
      return () => Vue.h('section', {class: ['ai-table', id]}, [
        Vue.h(ProUIBi.ProDataTable, {
          key: revision.value,
          autoScrollY: false,
          component,
          request: ctx => requestRows(tableKey, fields, props, ctx),
        }),
      ])
    },
  }))
}
