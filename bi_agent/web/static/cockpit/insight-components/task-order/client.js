function apiRoot(value) {
  return String(typeof value === 'function' ? value() : value || '').replace(/\/$/, '')
}

function identity(value) {
  const number = Number(typeof value === 'function' ? value() : value)
  return number === 2 ? 2 : 1
}

export function createTaskOrderClient({apiBase, identityId}) {
  async function request(path, options = {}) {
    const response = await fetch(`${apiRoot(apiBase)}${path}`, {
      ...options,
      headers: {Accept: 'application/json', 'Content-Type': 'application/json', ...(options.headers || {})},
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error(payload?.detail || `任务服务返回 ${response.status}`)
    }
    return payload
  }

  return {
    async draft(analysisId, recommendationIds) {
      return request(`/analyses/${encodeURIComponent(analysisId)}/draft`, {
        method: 'POST',
        body: JSON.stringify({id: identity(identityId), recommendationIds: recommendationIds.map(String)}),
      })
    },
    async listTasks() {
      return request('/tasks')
    },
    async save(taskId, revision, {title, goal, measures}) {
      return request(`/tasks/${encodeURIComponent(taskId)}`, {
        method: 'POST',
        body: JSON.stringify({
          id: identity(identityId), revision, action: 'save', title, goal,
          measures: measures.map(item => ({
            id: String(item.id || ''),
            action: String(item.action || '').trim(),
            owner: String(item.owner || '').trim(),
            deadline: String(item.deadline || '').trim(),
            acceptance: String(item.acceptance || '').trim(),
            ownerConfirmed: item.ownerConfirmed === true,
            deadlineConfirmed: item.deadlineConfirmed === true,
          })),
        }),
      })
    },
    async dispatch(taskId) {
      return request(`/tasks/${encodeURIComponent(taskId)}/dispatch`, {
        method: 'POST',
        body: JSON.stringify({id: identity(identityId), retry: false}),
      })
    },
  }
}

export function taskSelectionKey(ids) {
  return Array.from(new Set((ids || []).map(String))).sort().join('|')
}
