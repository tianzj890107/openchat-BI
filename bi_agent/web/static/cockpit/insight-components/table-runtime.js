/** Shared ProDataTable adapter for cached AP facts with validated AI columns. */
const { cockpitApiBase, cockpitIdentityId } = window.InsightRuntime

const RESULT_CACHE_LIMIT = 60
const REFRESH_WINDOW_MS = 5 * 60 * 1000
const resultCache = new Map()
const contentCache = new Map()
const lastRefreshed = new Map()

function remember(cache, key, value) {
  if (cache.has(key)) cache.delete(key)
  cache.set(key, value)
  while (cache.size > RESULT_CACHE_LIMIT) cache.delete(cache.keys().next().value)
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function pageScope(props) {
  const slot = props.slotProps || {}
  return String(slot.uiScope || slot.scopeKey || 'default')
}

function apQuery(ctx, fields, filterFields, sort) {
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
  const sorts = (sort || [])
    .filter(field => field && field.identifierCode)
    .map(field => ({identifierCode: field.identifierCode, order: field.order === 'DESC' ? 'DESC' : 'ASC'}))
  if (sorts.length) commonConfig.sorts = sorts
  const children = []
  const seen = new Set()
  for (const condition of [...filterFields.map(field => field.conditions).filter(Boolean), ...(ctx?.filters || [])]) {
    const signature = stable(condition)
    if (seen.has(signature)) continue
    seen.add(signature)
    children.push(condition)
  }
  if (children.length) commonConfig.filters = {logic: 'AND', children}
  return {analysisConfig: {dimensions, indicators}, commonConfig}
}

function contentSignature(tableKey, props, ctx, fields, filterFields, sort) {
  return stable({
    tableKey,
    scope: pageScope(props),
    fields: fields.map(field => field.identifierCode),
    sort: (sort || []).map(field => [field.identifierCode, field.order]),
    preFilters: filterFields.map(field => field.conditions),
    params: ctx?.params || {},
    filters: ctx?.filters || [],
  })
}

function querySignature(tableKey, props, ctx, fields, filterFields, sort) {
  return stable({
    content: contentSignature(tableKey, props, ctx, fields, filterFields, sort),
    analysis: [props.analysis?.id || '', props.analysis?.updatedAt || ''],
  })
}

async function requestRows(tableKey, fields, filterFields, sort, props, ctx, {cacheOnly=false} = {}) {
  const slot = props.slotProps || {}
  const apiBase = String(slot.apiBase || cockpitApiBase()).replace(/\/$/, '')
  const identityId = Number(slot.identityId) === 2 ? 2 : Number(slot.identityId) === 1 ? 1 : cockpitIdentityId()
  const response = await fetch(`${apiBase}/ai-tables/${encodeURIComponent(tableKey)}/query`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', Accept: 'application/json'},
    body: JSON.stringify({
      id: identityId,
      uiScope: pageScope(props),
      period: String(slot.period || ''),
      cacheOnly,
      ...apQuery(ctx, fields, filterFields, sort),
    }),
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload) throw new Error(payload?.detail || `表格查询失败 ${response.status}`)
  return {
    data: Array.isArray(payload.rows) ? payload.rows : [],
    total: Number(payload.total) || 0,
    meta: payload.meta || {},
  }
}

export function createTableInsight({id, name, title, tableKey, fields, columns, filterFields = [], sort = [], showTitle = false}) {
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
      const scopeState = Vue.ref('')
      const scopeError = Vue.ref('')
      const revision = Vue.ref(0)
      const component = Vue.markRaw({
        id: `insight-${id}`,
        type: 'table',
        title,
        showHeader: showTitle,
        showTitle,
        styleConfig: {showCurrentInfo: false},
        dataConfig: {
          pageSize: 10,
          sourceType: 'ap',
          tableFields: displayFields,
          ...(sort.length ? {sort} : {}),
          ...(filterFields.length ? {filter: filterFields} : {}),
        },
        tableColumnConfig: columns,
      })
      // Analysis timestamps change on every background publish even when the
      // rows are identical.  The table request signature still includes the
      // analysis id so annotations are refreshed, but the component instance
      // must survive so pagination, scroll and expanded rows are preserved.
      const componentKey = Vue.computed(() => `${pageScope(props)}:${revision.value}`)
      const refreshing = new Set()
      let lastContext = null

      async function refreshInBackground(ctx, signature) {
        if (refreshing.has(signature)) return
        const refreshedAt = Number(lastRefreshed.get(signature) || 0)
        if (Date.now() - refreshedAt < REFRESH_WINDOW_MS) return
        refreshing.add(signature)
        scopeState.value = '已显示上次保存的表格，正在后台更新'
        await new Promise(resolve => setTimeout(resolve, 300))
        try {
          const live = await requestRows(tableKey, fields, filterFields, sort, props, ctx)
          const contentKey = contentSignature(tableKey, props, ctx, fields, filterFields, sort)
          const previous = contentCache.get(contentKey)
          const changed = stable(live.data) !== stable(previous?.data || [])
          remember(contentCache, contentKey, live)
          remember(resultCache, signature, live)
          lastRefreshed.set(signature, Date.now())
          scopeError.value = ''
          if (changed) {
            scopeState.value = '表格数据已更新'
            revision.value += 1
          } else {
            scopeState.value = '表格已是最新版本'
          }
        } catch (cause) {
          scopeError.value = `后台更新失败，继续展示上次表格：${cause.message || cause}`
          scopeState.value = ''
        } finally {
          refreshing.delete(signature)
        }
      }

      async function request(ctx) {
        lastContext = ctx
        const signature = querySignature(tableKey, props, ctx, fields, filterFields, sort)
        const saved = resultCache.get(signature)
        if (saved) {
          scopeState.value = saved.meta?.cacheStatus === 'hit' ? '已加载上次保存的表格' : '表格数据已加载'
          return saved
        }
        try {
          scopeState.value = '正在读取已保存的表格'
          const cached = await requestRows(tableKey, fields, filterFields, sort, props, ctx, {cacheOnly: true})
          if (cached.meta?.cacheStatus === 'hit') {
            remember(contentCache, contentSignature(tableKey, props, ctx, fields, filterFields, sort), cached)
            remember(resultCache, signature, cached)
            scopeState.value = '已加载上次保存的表格'
            refreshInBackground(ctx, signature).catch(() => {})
            return cached
          }
          scopeState.value = '正在加载表格数据'
          const live = await requestRows(tableKey, fields, filterFields, sort, props, ctx)
          remember(contentCache, contentSignature(tableKey, props, ctx, fields, filterFields, sort), live)
          remember(resultCache, signature, live)
          lastRefreshed.set(signature, Date.now())
          scopeState.value = live.meta?.cacheStatus === 'refreshed' ? '表格数据已加载' : ''
          scopeError.value = ''
          return live
        } catch (cause) {
          scopeError.value = cause.message || String(cause)
          scopeState.value = ''
          throw cause
        }
      }

      // A new analysis publication may change the AI columns while leaving the
      // table facts untouched.  Refresh the request, but only bump the mount key
      // when the actual row content changes; timestamps alone must not reset
      // pagination, scroll or expanded rows.
      Vue.watch(() => [props.analysis?.id || '', props.analysis?.updatedAt || 0], () => {
        if (!lastContext || !props.analysis) return
        const signature = querySignature(tableKey, props, lastContext, fields, filterFields, sort)
        refreshInBackground(lastContext, signature).catch(() => {})
      }, {flush: 'post'})

      return () => Vue.h('section', {class: ['ai-table', id]}, [
        scopeState.value || scopeError.value
          ? Vue.h('div', {class: ['ai-table-state', scopeError.value ? 'ai-table-state--error' : ''], role: 'status'},
              scopeError.value || scopeState.value)
          : null,
        Vue.h(ProUIBi.ProDataTable, {
          key: componentKey.value,
          autoScrollY: false,
          component,
          request,
        }),
      ])
    },
  }))
}
