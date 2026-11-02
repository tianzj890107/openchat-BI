import React, { useEffect, useMemo, useState } from "react";
import {
  CheckCircleFilled,
  ClockCircleOutlined,
  ExclamationCircleFilled,
  LoadingOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";
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

function StatusGlyph({ status }) {
  if (status === AGENT_STATUS.RUNNING) return <LoadingOutlined spin />;
  if (status === AGENT_STATUS.AWAITING_CHOICE) return <PauseCircleOutlined />;
  if (status === AGENT_STATUS.COMPLETED) return <CheckCircleFilled />;
  if (status === AGENT_STATUS.FAILED || status === AGENT_STATUS.SUPERSEDED) {
    return <ExclamationCircleFilled />;
  }
  if (status === AGENT_STATUS.INTERRUPTED) return <PauseCircleOutlined />;
  return <ClockCircleOutlined />;
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
      <span className="pro-ui-agent-status-glyph" aria-hidden="true">
        <StatusGlyph status={activity.status} />
      </span>
      <span className="pro-ui-agent-status-copy">
        <strong>{label}</strong>
        {detail ? <span>{detail}</span> : null}
      </span>
      {runningCount > 1 ? (
        <span className="pro-ui-agent-status-count">{runningCount} 个步骤</span>
      ) : null}
      {primary?.name && activity.status === AGENT_STATUS.RUNNING ? (
        <span className="pro-ui-agent-status-tool">{primary.name}</span>
      ) : null}
      {canStop ? (
        <button
          type="button"
          className="pro-ui-agent-status-stop"
          onClick={() => window.dispatchEvent(new CustomEvent("bi-stop-generation"))}
        >
          停止
        </button>
      ) : null}
    </div>
  );
}
