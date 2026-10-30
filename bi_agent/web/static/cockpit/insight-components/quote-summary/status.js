// Read exact AP row fields; claim labels do not carry a status or a reliable unit.
export function quotationStatus(records = []) {
  const values = {}, seen = new Set()
  for (const record of records) {
    const row = record?.data || {}
    const cell = code => {
      const key = Object.keys(row).find(key => key === code || key.endsWith(`[${code}]`))
      const value = row[key]
      return value && typeof value === 'object' ? value.value : value
    }
    const status = cell('YWLN_D021'), raw = cell('YWLN_M0031')
    if (!['normal_completed','overdue_completed','overdue_uncompleted','imminent_uncompleted','normal_uncompleted'].includes(status)
      || raw === null || raw === undefined || raw === '' || !Number.isFinite(Number(raw))) continue
    const key = JSON.stringify([record.scope?.request || {}, status, raw])
    if (seen.has(key)) continue
    seen.add(key)
    values[status] = (values[status] || 0) + Number(raw)
  }
  const sum = keys => {
    const present = keys.filter(key => key in values)
    return present.length ? Number(present.reduce((total,key) => total + values[key], 0).toFixed(10)) : null
  }
  return {values, total: sum(Object.keys(values)),
    completed: sum(['normal_completed','overdue_completed']),
    pending: sum(['overdue_uncompleted','imminent_uncompleted','normal_uncompleted'])}
}
