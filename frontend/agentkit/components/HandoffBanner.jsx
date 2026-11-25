import React from "react";

function FilterChips({filters}) {
  const entries = Object.entries(filters || {});
  if (!entries.length) return null;
  return (
    <ul className="ak-chips">
      {entries.map(([key, value]) => (
        <li key={key} className="ak-chip">
          {key}: {String(value)}
        </li>
      ))}
    </ul>
  );
}

/**
 * V6.1 handoff banner: shows the carried context, and turns an unusable
 * handoff into an explicit choice instead of an empty page (spec §3.2).
 */
export default function HandoffBanner({handoff, confirmed, onDismiss, onBack, onRestart}) {
  if (!handoff?.active) return null;

  if (handoff.invalid) {
    return (
      <div className="ak-handoff ak-handoff--invalid" role="alert" data-agentkit-handoff="invalid">
        <div>
          <strong>这张卡片带来的分析范围无法使用</strong>
          <p>{handoff.reason}</p>
        </div>
        <div className="ak-handoff-actions">
          <button type="button" className="ak-ghost" onClick={onBack}>
            返回来源卡
          </button>
          <button type="button" className="ak-primary" onClick={onRestart}>
            重新发起分析
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="ak-handoff" data-agentkit-handoff="ok">
      <div>
        <strong>已从来源卡带入分析范围</strong>
        <p>{handoff.summary}</p>
        <FilterChips filters={handoff.filters} />
        {handoff.evidence.length ? (
          <p className="ak-handoff-evidence">证据引用：{handoff.evidence.join("、")}</p>
        ) : null}
        {confirmed ? (
          <p className="ak-handoff-confirmed" role="status">
            分析服务已核对范围：锚点 {confirmed.anchor || "—"} · 期间 {confirmed.period || "—"}
          </p>
        ) : null}
        <p className="ak-handoff-note">以下分析会按当前期间与筛选重新核对口径，可在提问中继续补充条件。</p>
      </div>
      <div className="ak-handoff-actions">
        <button type="button" className="ak-primary" onClick={onDismiss}>
          按此范围继续
        </button>
      </div>
    </div>
  );
}
