import React from "react";

/** Conversation list: AgentKit thread-list conventions over this repo's API. */
export default function SessionList({conversations, activeId, onNew, onSelect}) {
  return (
    <div className="ak-sessions-inner">
      <button type="button" className="ak-new" onClick={onNew}>
        新建会话
      </button>
      {conversations.length === 0 ? (
        <p className="ak-sessions-empty">还没有历史会话。新建一个并开始提问。</p>
      ) : (
        <ul className="ak-session-items">
          {conversations.map((item) => {
            const id = String(item.id ?? item.cid ?? "");
            const title = item.title || item.preview || "未命名会话";
            return (
              <li key={id}>
                <button
                  type="button"
                  className="ak-session"
                  data-active={id === activeId ? "1" : undefined}
                  onClick={() => onSelect(id)}
                  title={title}
                >
                  <span className="ak-session-title">{title}</span>
                  {item.updated_at || item.created_at ? (
                    <span className="ak-session-time">{String(item.updated_at || item.created_at).slice(0, 16)}</span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
