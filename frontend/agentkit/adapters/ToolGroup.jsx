import React, {useCallback, useRef, useState} from "react";
import {Collapsible, CollapsibleContent, CollapsibleTrigger} from "@radix-ui/react-collapsible";
import {ChevronDownIcon, LoaderIcon} from "lucide-react";
import {useScrollLock} from "@assistant-ui/react";

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

function ToolItem({tool}) {
  return (
    <li className="ak-tool" data-status={tool.status} data-slot="tool-group-item">
      <span className="ak-tool-name">{tool.name}</span>
      <span className="ak-tool-state">
        {tool.status === "running" ? "执行中…" : tool.output ? "已完成" : "已调用"}
      </span>
      {tool.input ? <code className="ak-tool-input">{tool.input}</code> : null}
    </li>
  );
}

export default function ToolGroup({tools}) {
  const running = tools.some((tool) => tool.status === "running");
  return (
    <ToolGroupRoot defaultOpen={running}>
      <ToolGroupTrigger count={tools.length} active={running} />
      <ToolGroupContent>
        <ol className="ak-tool-list">
          {tools.map((tool) => (
            <ToolItem key={tool.id} tool={tool} />
          ))}
        </ol>
      </ToolGroupContent>
    </ToolGroupRoot>
  );
}
