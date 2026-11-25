import React, {useCallback, useRef, useState} from "react";
import {Collapsible, CollapsibleContent, CollapsibleTrigger} from "@radix-ui/react-collapsible";
import {ChevronDownIcon, LoaderIcon} from "lucide-react";
import {useScrollLock} from "@assistant-ui/react";
import {toolOntologyHits} from "../results.js";

// Adapted from AgentKit `tool-group.aui.tsx`
// (agentkit-ui/src/components/assistant-ui/elements/tool-group.aui.tsx at the
// pinned upstream commit).  The upstream structure is kept — Root / Trigger /
// Content, data-slot markers, count label from the upstream util — while the
// Tailwind classes are replaced by the workbench's own `ak-tools` styles so the
// page renders without a Tailwind pipeline.
import {toolGroupCountLabel} from "../upstream/agentkit-ui/src/components/assistant-ui/utils/tool-display-label";

const ANIMATION_DURATION = 200;

export function ToolGroupRoot({open, defaultOpen = false, onOpenChange, children, ...props}) {
  const ref = useRef(null);
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const lockScroll = useScrollLock(ref, ANIMATION_DURATION);
  const isControlled = open !== undefined;
  const isOpen = isControlled ? open : uncontrolledOpen;

  const handleOpenChange = useCallback(
    (next) => {
      lockScroll();
      if (!isControlled) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [lockScroll, isControlled, onOpenChange],
  );

  return (
    <Collapsible
      ref={ref}
      data-slot="tool-group-root"
      open={isOpen}
      onOpenChange={handleOpenChange}
      className="ak-tools"
      style={{"--animation-duration": `${ANIMATION_DURATION}ms`}}
      {...props}
    >
      {children}
    </Collapsible>
  );
}

export function ToolGroupTrigger({count, active = false}) {
  return (
    <CollapsibleTrigger data-slot="tool-group-trigger" className="ak-tools-trigger">
      {active ? <LoaderIcon data-slot="tool-group-trigger-loader" className="ak-tools-spinner" /> : null}
      <span data-slot="tool-group-trigger-label" className="ak-tools-label">
        {toolGroupCountLabel(count)}
      </span>
      <ChevronDownIcon data-slot="tool-group-trigger-chevron" className="ak-tools-chevron" />
    </CollapsibleTrigger>
  );
}

export function ToolGroupContent({children}) {
  return (
    <CollapsibleContent data-slot="tool-group-content" className="ak-tools-content">
      {children}
    </CollapsibleContent>
  );
}

function ToolValue({label, value}) {
  if (value == null || value === "") return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="ak-tool-value">
      <strong>{label}</strong>
      <pre>{text}</pre>
    </div>
  );
}

function ToolItem({tool, active, onOpenOntology}) {
  const hits = toolOntologyHits(tool);
  const failed = Boolean(tool.errorCode || /FAIL|ERROR/i.test(tool.executionStatus || ""));
  const state = failed ? "失败" : tool.status === "running" ? (active ? "执行中…" : "未完成") : "已完成";
  return (
    <li className="ak-tool" data-status={failed ? "error" : tool.status} data-slot="tool-group-item">
      <details>
        <summary className="ak-tool-summary">
          <strong className="ak-tool-name">{tool.name}</strong>
          <span className="ak-tool-state">
            {state}{Number.isFinite(tool.durationMs) ? ` · ${tool.durationMs} ms` : ""}
            {hits.length ? ` · 命中 ${hits.length} 个本体` : ""}
          </span>
        </summary>
        <div className="ak-tool-detail">
          {tool.errorCode ? <p className="ak-tool-error">错误代码 {tool.errorCode}</p> : null}
          {tool.attempt ? <p className="ak-tool-state">第 {tool.attempt} 次执行</p> : null}
          <ToolValue label="调用入参" value={tool.input} />
          <ToolValue label="返回内容" value={tool.output} />
          {hits.length ? (
            <section aria-label="本体命中">
              <h4 className="ak-section-title">本体命中</h4>
              <ul className="ak-hits">
                {hits.map((hit) => (
                  <li key={`${hit.repositoryId}:${hit.code}`}>
                    <button type="button" className="ak-hit" data-ontology-code={hit.code} onClick={() => onOpenOntology(hit)}>
                      <span className="ak-hit-name">{hit.name}</span>
                      <span className="ak-hit-code">{hit.code}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </details>
    </li>
  );
}

export default function ToolGroup({tools, active, onOpenOntology}) {
  const running = active && tools.some((tool) => tool.status === "running");
  return (
    <ToolGroupRoot defaultOpen={running}>
      <ToolGroupTrigger count={tools.length} active={running} />
      <ToolGroupContent>
        <ol className="ak-tool-list">
          {tools.map((tool) => (
            <ToolItem key={tool.id} tool={tool} active={active} onOpenOntology={onOpenOntology} />
          ))}
        </ol>
      </ToolGroupContent>
    </ToolGroupRoot>
  );
}
