/* Shared stage work is shown on every card in that stage. No new polling. */
export function taskProgressText(manual, stage, now = Date.now()) {
  const work = manual.stageProgress?.[stage];
  if (!work) {
    if (manual.running && manual.activeStage === stage) return manual.progress?.message || '后台更新中';
    if (manual.running && manual.pendingStages?.includes(stage)) return '排队等待';
    return manual.failedStages?.some(item => item.stage === stage) ? '沿用上次结果' : '';
  }
  const started = Number(work.startedAt || work.queuedAt || 0) * 1000;
  const end = work.finishedAt ? Number(work.finishedAt)*1000 : now;
  const elapsed = started ? Math.max(0, Math.floor((end-started)/1000)) : 0;
  const time = elapsed >= 60 ? `${Math.floor(elapsed/60)}分${elapsed%60}秒` : `${elapsed}秒`;
  let label;
  if (work.status === 'failed') label = '更新未完成，沿用上次结果';
  else if (work.status === 'completed') label = '已更新';
  else if (work.status === 'queued') label = '排队等待';
  else if (work.phase === 'fetching') label = `取数${Number.isFinite(work.total) ? ` ${work.completed || 0}/${work.total}` : ''}`;
  else if (work.phase === 'publishing') label = '发布中';
  else label = work.message || '分析中';
  return `${label} · ${work.status === 'queued' ? '已等待' : '耗时'} ${time}`;
}
