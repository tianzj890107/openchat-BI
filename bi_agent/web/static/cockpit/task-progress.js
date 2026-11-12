/* Shared stage work is shown on every card in that stage. No new polling. */
export function taskProgressText(manual, stage, now = Date.now()) {
  const phaseLabels = {
    ontology: '读取本体',
    fetching: '查询数据库',
    ap: 'AP 补充',
    rules: '规则计算',
    analysing: '原因分析',
    publishing: '发布中',
    published: '已发布',
  };
  const work = manual.stageProgress?.[stage];
  if (!work) {
    if (manual.running && manual.activeStage === stage) return manual.progress?.message || '后台更新中';
    if (manual.running && manual.pendingStages?.includes(stage)) return '排队等待';
    return manual.failedStages?.some(item => item.stage === stage) ? '分析失败，本轮无结果' : '';
  }
  const started = Number(work.startedAt || work.queuedAt || 0) * 1000;
  const end = work.finishedAt ? Number(work.finishedAt)*1000 : now;
  const elapsed = started ? Math.max(0, Math.floor((end-started)/1000)) : 0;
  const duration = value => value >= 60 ? `${Math.floor(value/60)}分${value%60}秒` : `${value}秒`;
  const time = duration(elapsed);
  const stepStarted = Number(work.stepStartedAt || 0) * 1000;
  const stepElapsed = work.status === 'running' && stepStarted
    ? Math.max(0, Math.floor((now-stepStarted)/1000)) : 0;
  const step = stepElapsed ? ` · 本步 ${duration(stepElapsed)}` : '';
  const query = work.query ? ` · ${work.query}` : '';
  const querySeconds = Number(work.queryDurationSeconds)
  const queryTime = Number.isFinite(querySeconds) && querySeconds >= 0
    ? ` · 本查询 ${duration(Math.round(querySeconds))}` : '';
  let label;
  if (work.status === 'failed') label = '分析失败，本轮无结果';
  else if (work.status === 'completed') label = '已更新';
  else if (work.status === 'queued') label = '排队等待';
  else if (work.phase === 'fetching') label = `查询数据库${Number.isFinite(work.total) ? ` ${work.completed || 0}/${work.total}` : ''}${query}${queryTime}`;
  else label = work.message || phaseLabels[work.phase] || '分析中';
  if (work.status === 'running' && stepStarted) return `${label}${step} · 总耗时 ${time}`;
  return `${label} · ${work.status === 'queued' ? '已等待' : '耗时'} ${time}`;
}

const FAILURE_STAGE_LABELS = {
  'opportunity-risk': '商机获取 · 风险分析卡', opportunity: '商机获取 · 商机推进与覆盖缺口卡',
  quotation: '报价', bid: '投标',
  order: '订单接收', shipment: '发货', combined: '销售额与出货量跨环节共同问题分析',
};

/* Failures of a round this page saw running; each stage is announced once. */
export function newStageFailures(manual, watch) {
  const runId = String(manual?.runId || '');
  if (!runId) return [];
  if (manual.status === 'running') watch.runId = runId;
  if (watch.runId !== runId) return [];
  const fresh = [];
  for (const [stage, work] of Object.entries(manual.stageProgress || {})) {
    const key = `${runId}:${stage}`;
    if (work?.status !== 'failed' || watch.announced.has(key)) continue;
    watch.announced.add(key);
    fresh.push({
      key,
      stage: FAILURE_STAGE_LABELS[stage] || stage,
      message: work.error || manual.error || '分析失败，本轮未发布，卡片已清空，请稍后重试。',
      diagnosticId: work.diagnosticId || '',
      details: (Array.isArray(work.errorDetails) ? work.errorDetails : [])
        .filter(section => section && Array.isArray(section.lines) && section.lines.length)
        .map(section => ({title: String(section.title || '详细信息'), lines: section.lines.map(String)})),
    });
  }
  return fresh;
}

/* Plain text of one failure, for copying into a ticket or chat. */
export function failureText(item) {
  const parts = [`【${item.stage}】`, item.message];
  for (const section of item.details || []) {
    parts.push('', `[${section.title}]`, ...section.lines.map(line => `- ${line}`));
  }
  if (item.diagnosticId) parts.push('', `诊断ID：${item.diagnosticId}`);
  return parts.join('\n');
}
