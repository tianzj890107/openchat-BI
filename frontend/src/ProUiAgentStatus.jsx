import React, { useEffect, useMemo, useState } from "react";
import { Button as ProXButton, ProXThreadStatus } from "@pro-ui/x-react";
import {
  AGENT_STATUS,
  createAgentActivityState,
  getPrimaryActivity,
  getStatusDetail,
  getStatusLabel,
} from "./agentActivityModel.js";

function initialActivity() {
  try {
    return window.__biAgentActivityState || createAgentActivityState();
  } catch (_) {
    return createAgentActivityState();
  }
}

function threadStatusPhase(status) {
  if (status === AGENT_STATUS.RUNNING) return "running";
  if (status === AGENT_STATUS.AWAITING_CHOICE) return "awaiting_resume";
  if (status === AGENT_STATUS.FAILED || status === AGENT_STATUS.SUPERSEDED) return "error";
  return "idle";
}

export default function ProUiAgentStatus() {
  const [activity, setActivity] = useState(initialActivity);

  useEffect(() => {
    const onActivity = (event) => {
      const next = event?.detail?.state;
      if (next) setActivity(next);
    };
    window.addEventListener("bi-agent-activity", onActivity);
    return () => window.removeEventListener("bi-agent-activity", onActivity);
  }, []);

  const primary = useMemo(() => getPrimaryActivity(activity), [activity]);
  if (!activity || activity.status === AGENT_STATUS.IDLE) return null;

  const label = getStatusLabel(activity);
  const detail = getStatusDetail(activity);
  const runningCount = activity.activities.filter((item) => item.status === "running").length;
  const canStop = activity.busy && activity.status === AGENT_STATUS.RUNNING;

  return (
    <div
      className={`pro-ui-agent-status pro-ui-agent-status-${activity.status}`}
      data-status={activity.status}
      role="status"
      aria-live="polite"
    >
      <ProXThreadStatus
        phase={threadStatusPhase(activity.status)}
        label={label}
        description={detail}
        hideWhenIdle={false}
      />
      {runningCount > 1 ? (
        <span className="pro-ui-agent-status-count">{runningCount} 个步骤</span>
      ) : null}
      {primary?.name && activity.status === AGENT_STATUS.RUNNING ? (
        <span className="pro-ui-agent-status-tool">{primary.name}</span>
      ) : null}
      {canStop ? (
        <ProXButton
          className="pro-ui-agent-status-stop"
          onClick={() => window.dispatchEvent(new CustomEvent("bi-stop-generation"))}
        >
          停止
        </ProXButton>
      ) : null}
    </div>
  );
}
