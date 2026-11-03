import React, { useEffect, useMemo, useState } from "react";
import { Tag } from "antd";
import { Prompts, Welcome } from "@ant-design/x";
import { welcomePromptsFromHints } from "./proUiBridge.js";

function readWelcome() {
  const empty = document.getElementById("chat-empty");
  const hints = [...(document.getElementById("empty-hints")?.querySelectorAll(".hint-val") || [])]
    .map((node) => node.textContent?.trim() || "")
    .filter(Boolean);
  return {
    visible: !!empty && empty.style.display !== "none",
    title: document.getElementById("empty-title")?.textContent?.trim() || "硕磐智能分析 Agent",
    description: document.getElementById("empty-welcome")?.textContent?.trim()
      || "用自然语言问数据、查本体、生成图表，并把结论沉淀到实时看板。",
    hints,
  };
}

function BrandMark() {
  return (
    <span className="pro-ui-welcome-mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M12 2.8 14.3 8l5.7 1.1-4.2 3.9 1.1 5.6-4.9-2.7-4.9 2.7 1.1-5.6L4 9.1 9.7 8 12 2.8Z" fill="currentColor" opacity=".16" />
        <path d="M12 5.4 13.6 9l3.8.7-2.8 2.6.7 3.7-3.3-1.8-3.3 1.8.7-3.7L6.6 9.7 10.4 9 12 5.4Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export default function ProUiWelcome() {
  const [data, setData] = useState(readWelcome);
  useEffect(() => {
    const empty = document.getElementById("chat-empty");
    const hints = document.getElementById("empty-hints");
    const scroll = document.getElementById("chat-scroll");
    let frame = 0;
    const sync = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => setData(readWelcome()));
    };
    const observer = new MutationObserver(sync);
    [empty, hints, scroll].filter(Boolean).forEach((node) => observer.observe(node, {
      attributes: true,
      childList: true,
      subtree: true,
      characterData: true,
    }));
    sync();
    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  const prompts = useMemo(() => welcomePromptsFromHints(data.hints), [data.hints]);
  if (!data.visible) return null;

  return (
    <div className="pro-ui-welcome-shell">
      <Welcome
        variant="borderless"
        icon={<BrandMark />}
        title={<span className="pro-ui-welcome-title">{data.title}</span>}
        description={data.description}
        extra={<Tag bordered={false} className="pro-ui-version-tag">ontology-v0.1.5</Tag>}
      />
      {prompts.length ? (
        <Prompts
          className="pro-ui-welcome-prompts"
          title="可以这样开始"
          vertical
          items={prompts.map((item) => ({
            key: item.key,
            label: item.label,
            description: item.description,
            icon: <span className="pro-ui-prompt-arrow" aria-hidden="true">↗</span>,
          }))}
          onItemClick={({ data: prompt }) => {
            window.dispatchEvent(new CustomEvent("bi-composer-prefill", {
              detail: { text: String(prompt.label || "") },
            }));
          }}
        />
      ) : null}
    </div>
  );
}
