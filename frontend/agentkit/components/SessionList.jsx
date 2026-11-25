import React, {useState} from "react";

import {changeTrash, loadTrash} from "../api.js";
import {SettingsDialog} from "./Settings.jsx";

function RecycleBin({onClose, onRefresh}) {
  const [bin, setBin] = useState(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = async () => {
    setBusy(true);
    try { setBin(await loadTrash()); setNotice(""); }
    catch (error) { setNotice(error.message); }
    finally { setBusy(false); }
  };
  React.useEffect(() => { void refresh(); }, []);
  const change = async (action, item) => {
    if (action === "purge" && !window.confirm(`永久删除「${item.title}」？`)) return;
    if (action === "empty" && !window.confirm("永久删除回收站里的全部会话？")) return;
    setBusy(true);
    try {
      await changeTrash(action, item?.id);
      await refresh();
      await onRefresh();
    } catch (error) { setNotice(error.message); }
    finally { setBusy(false); }
  };
  const entries = bin?.trash || [];
  return <SettingsDialog title="会话回收站" onClose={onClose}>
    <p className="ak-settings-hint">{bin ? `会话保留 ${bin.retention_days} 天` : busy ? "正在加载…" : ""}</p>
    {notice ? <p role="alert">{notice}</p> : null}
    {bin && !entries.length ? <p className="ak-settings-hint">回收站为空</p> : null}
    <ul className="ak-session-items">
      {entries.map((item) => <li key={item.id} className="ak-trash-item">
        <span>{item.title || "未命名会话"} · {item.days_left ?? "—"} 天后清除</span>
        <button type="button" className="ak-ghost" disabled={busy} onClick={() => change("restore", item)}>恢复</button>
        <button type="button" className="ak-ghost" disabled={busy} onClick={() => change("purge", item)}>永久删除</button>
      </li>)}
    </ul>
    <button type="button" className="ak-ghost" disabled={busy || !entries.length} onClick={() => change("empty")}>清空回收站</button>
  </SettingsDialog>;
}

export default function SessionList({conversations, activeId, onNew, onSelect, onRefresh, onRemoved, busy}) {
  const [query, setQuery] = useState("");
  const [trash, setTrash] = useState(false);
  const [pending, setPending] = useState("");
  const [notice, setNotice] = useState("");
  const search = query.trim().toLowerCase();
  const visible = conversations.filter((item) => [item.title, item.preview, item.first_user_question]
    .some((value) => String(value || "").toLowerCase().includes(search)));
  const remove = async (id, title) => {
    if (!window.confirm(`将「${title}」移入回收站？`)) return;
    setPending(id);
    setNotice("");
    try {
      await changeTrash("remove", id);
      onRemoved(id);
      await onRefresh();
    } catch (error) { setNotice(error.message); }
    finally { setPending(""); }
  };
  return (
    <div className="ak-sessions-inner">
      <button type="button" className="ak-new" onClick={onNew} disabled={busy}>新建会话</button>
      <div className="ak-session-search">
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话" aria-label="搜索会话" />
        <button type="button" className="ak-ghost" aria-label="刷新会话" title="刷新会话" onClick={onRefresh}>↻</button>
        <button type="button" className="ak-ghost" onClick={() => setTrash(true)}>回收站</button>
      </div>
      {notice ? <p role="alert">{notice}</p> : null}
      {visible.length === 0 ? <p className="ak-sessions-empty">{search ? "没有匹配的会话" : "还没有历史会话。新建一个并开始提问。"}</p> : (
        <ul className="ak-session-items">
          {visible.map((item) => {
            const id = String(item.id ?? item.cid ?? "");
            const title = item.title || item.preview || "未命名会话";
            return (
              <li key={id} className="ak-session-row">
                <button type="button" className="ak-session" data-active={id === activeId ? "1" : undefined}
                  disabled={busy || !!pending} onClick={() => onSelect(id)} title={title}>
                  <span className="ak-session-title">{title}</span>
                  {item.updated_at || item.created_at ? <span className="ak-session-time">{String(item.updated_at || item.created_at).slice(0, 16)}</span> : null}
                </button>
                <button type="button" className="ak-ghost ak-trash-trigger" disabled={busy || !!pending} onClick={() => remove(id, title)}
                  aria-label={`移入回收站：${title}`} title="移入回收站">×</button>
              </li>
            );
          })}
        </ul>
      )}
      {trash ? <RecycleBin onClose={() => setTrash(false)} onRefresh={onRefresh} /> : null}
    </div>
  );
}
