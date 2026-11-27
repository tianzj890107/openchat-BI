import React, {useState} from "react";

export default function SessionList({conversations, activeId, onNew, onSelect, onRefresh, busy}) {
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const search = query.trim().toLowerCase();
  const visible = conversations.filter((item) => [item.title, item.preview, item.first_user_question]
    .some((value) => String(value || "").toLowerCase().includes(search)));
  return (
    <div className="ak-sessions-inner">
      <button type="button" className="ak-new" onClick={onNew} disabled={busy}>新建会话</button>
      <input type="search" className="ak-session-search" value={query}
        onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话" aria-label="搜索会话" />
      {notice ? <p role="alert">{notice}</p> : null}
      {visible.length === 0 ? <p className="ak-sessions-empty">{search ? "没有匹配的会话" : "还没有历史会话。新建一个并开始提问。"}</p> : (
        <ul className="ak-session-items">
          {visible.map((item) => {
            const id = String(item.id ?? item.cid ?? "");
            const title = item.title || item.preview || "未命名会话";
            return (
              <li key={id} className="ak-session-row">
                <button type="button" className="ak-session" data-active={id === activeId ? "1" : undefined}
                  disabled={busy} onClick={() => onSelect(id)} title={title}>
                  <span className="ak-session-title">{title}</span>
                  {item.updated_at || item.created_at ? <span className="ak-session-time">{String(item.updated_at || item.created_at).slice(0, 16)}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
