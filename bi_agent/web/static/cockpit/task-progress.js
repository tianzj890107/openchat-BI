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
    return manual.failedStages?.some(item => item.stage === stage) ? '沿用上次结果' : '';
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
  let label;
  if (work.status === 'failed') label = '更新未完成，沿用上次结果';
  else if (work.status === 'completed') label = '已更新';
  else if (work.status === 'queued') label = '排队等待';
  else if (work.phase === 'fetching') label = `查询数据库${Number.isFinite(work.total) ? ` ${work.completed || 0}/${work.total}` : ''}`;
  else label = work.message || phaseLabels[work.phase] || '分析中';
  if (work.status === 'running' && stepStarted) return `${label}${step} · 总耗时 ${time}`;
  return `${label} · ${work.status === 'queued' ? '已等待' : '耗时'} ${time}`;
}
