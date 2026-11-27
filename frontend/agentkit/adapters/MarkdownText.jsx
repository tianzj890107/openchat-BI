import React from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Assistant body renderer (AgentKit `markdown-text.tsx` role).
 *
 * Raw HTML is not enabled: the analysis backend returns Markdown only, so
 * rendering it with react-markdown (GFM tables/lists) stays XSS-safe without a
 * sanitizer step.
 */
export default function MarkdownText({text}) {
  const source = String(text || "");
  if (!source.trim()) return null;
  return (
    <div className="ak-answer ak-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{source}</Markdown>
    </div>
  );
}
