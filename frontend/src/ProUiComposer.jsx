import React, { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Switch, Tooltip } from "antd";
import {
  Button as ProXButton,
  ProXAttachments,
  ProXSender,
} from "@pro-ui/x-react";
import {
  DatabaseOutlined,
  HistoryOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import {
  composerActionState,
  normalizeComposerValue,
} from "./proUiBridge.js";

function legacyElement(id) {
  return document.getElementById(id);
}

function clickLegacy(id) {
  legacyElement(id)?.click();
}

function readLegacySnapshot() {
  const input = legacyElement("chat-input");
  const mode = document.body.dataset.mode || "data";
  const busy = !!legacyElement("btn-send")?.classList.contains("is-busy");
  const attachRow = legacyElement("attach-row");
  return {
    value: input?.value || "",
    busy,
    disabled: !!input?.disabled,
    placeholder: input?.placeholder || "提问…",
    mode,
    withDb: !!legacyElement("with-db")?.checked,
    historyCount: Number(legacyElement("history-count")?.textContent || 0),
    attachVisible: !!attachRow && !attachRow.hidden,
    attachName: legacyElement("attach-chip-name")?.textContent?.trim() || "",
    attachMeta: legacyElement("attach-chip-meta")?.textContent?.trim() || "",
    uploadStatus: legacyElement("upload-status")?.textContent?.trim() || "",
  };
}

export default function ProUiComposer() {
  const senderRef = useRef(null);
  const [snapshot, setSnapshot] = useState(readLegacySnapshot);
  const [value, setValue] = useState(() => readLegacySnapshot().value);
  const state = composerActionState({
    value,
    busy: snapshot.busy,
    disabled: snapshot.disabled,
  });

  useEffect(() => {
    let frame = 0;
    const sync = () => {
      const next = readLegacySnapshot();
      setSnapshot((previous) => {
        const same = Object.keys(next).every((key) => previous[key] === next[key]);
        return same ? previous : next;
      });
      setValue((previous) => (
        normalizeComposerValue(previous) === normalizeComposerValue(next.value)
          ? previous
          : next.value
      ));
      frame = window.setTimeout(sync, 320);
    };
    sync();
    const onBusy = (event) => {
      setSnapshot((previous) => ({ ...previous, busy: !!event.detail?.busy }));
    };
    const onMode = () => {
      const next = readLegacySnapshot();
      setSnapshot(next);
      setValue(next.value);
    };
    const onPrefill = (event) => {
      const next = normalizeComposerValue(event.detail?.text);
      setValue(next);
      const input = legacyElement("chat-input");
      if (input) {
        input.value = next;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      window.requestAnimationFrame(() => senderRef.current?.focus?.());
    };
    const onFocus = () => senderRef.current?.focus?.();
    window.addEventListener("bi-agent-busy", onBusy);
    window.addEventListener("bi-mode-changed", onMode);
    window.addEventListener("bi-composer-prefill", onPrefill);
    window.addEventListener("bi-composer-focus", onFocus);
    return () => {
      window.clearTimeout(frame);
      window.removeEventListener("bi-agent-busy", onBusy);
      window.removeEventListener("bi-mode-changed", onMode);
      window.removeEventListener("bi-composer-prefill", onPrefill);
      window.removeEventListener("bi-composer-focus", onFocus);
    };
  }, []);

  const writeLegacyValue = (next) => {
    const input = legacyElement("chat-input");
    if (!input) return;
    input.value = next;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  };

  const handleChange = (next) => {
    setValue(next);
    writeLegacyValue(next);
  };

  const handleSubmit = (submittedValue) => {
    const next = normalizeComposerValue(submittedValue);
    if (!next.trim() || snapshot.busy || snapshot.disabled) return;
    writeLegacyValue(next);
    clickLegacy("btn-send");
    setValue("");
  };

  const handleCancel = () => {
    window.dispatchEvent(new CustomEvent("bi-stop-generation"));
  };

  const toggleDb = (checked) => {
    const checkbox = legacyElement("with-db");
    if (!checkbox) return;
    checkbox.checked = checked;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    setSnapshot((previous) => ({ ...previous, withDb: checked }));
  };

  const attachments = useMemo(() => {
    if (!snapshot.attachVisible) return [];
    return [{
      uid: "active-report",
      name: snapshot.attachName || "已激活报表",
      description: snapshot.attachMeta || "当前分析报表",
      status: "done",
      cardType: "file",
    }];
  }, [snapshot.attachMeta, snapshot.attachName, snapshot.attachVisible]);

  const attachmentHeader = attachments.length ? (
    <div className="pro-ui-composer-attachments">
      <ProXAttachments
        items={attachments}
        overflow="wrap"
        showUploadList={{ showRemoveIcon: true }}
        onRemove={() => {
          clickLegacy("attach-chip-remove");
          return true;
        }}
        children={null}
      />
      <ProXButton
        type="text"
        size="small"
        onClick={() => clickLegacy("attach-chip-change")}
      >
        切换报表
      </ProXButton>
    </div>
  ) : null;

  const footer = (
    <div className="pro-ui-composer-footer">
      <div className="pro-ui-composer-tools">
        {snapshot.mode === "report" ? (
          <>
            <Tooltip title="上传 PDF / Word 报表">
              <ProXButton
                size="small"
                type="text"
                icon={<PaperClipOutlined />}
                onClick={() => clickLegacy("btn-attach")}
              >
                上传报表
              </ProXButton>
            </Tooltip>
            <Tooltip title="问答同时调用本体工具与 SQL 对账">
              <label className="pro-ui-db-switch">
                <DatabaseOutlined />
                <span>数据库查询</span>
                <Switch size="small" checked={snapshot.withDb} onChange={toggleDb} />
              </label>
            </Tooltip>
            <Tooltip title="最近上传的报表">
              <Badge count={snapshot.historyCount} size="small" offset={[-2, 1]}>
                <ProXButton
                  size="small"
                  type="text"
                  icon={<HistoryOutlined />}
                  onClick={() => clickLegacy("btn-history")}
                >
                  最近报表
                </ProXButton>
              </Badge>
            </Tooltip>
            <Tooltip title="按经营规则配置生成标准管报">
              <ProXButton
                size="small"
                type="text"
                icon={<PlusOutlined />}
                onClick={() => clickLegacy("btn-reportgen")}
              >
                报表生成
              </ProXButton>
            </Tooltip>
          </>
        ) : null}
        <span className="pro-ui-upload-status">{snapshot.uploadStatus}</span>
      </div>
      <span className="pro-ui-composer-hint">
        {snapshot.attachVisible ? (
          <ProXButton type="link" size="small" icon={<ReloadOutlined />} onClick={() => clickLegacy("btn-history")}>
            切换报表
          </ProXButton>
        ) : null}
        Enter 发送 · Shift + Enter 换行
      </span>
    </div>
  );

  return (
    <div className="pro-ui-composer-shell" data-mode={snapshot.mode}>
      <ProXSender
        ref={senderRef}
        className="pro-ui-sender"
        value={value}
        layout="vertical"
        loading={snapshot.busy}
        disabled={snapshot.disabled}
        submitDisabled={!state.canSubmit}
        placeholder={snapshot.placeholder}
        autoSize={{ minRows: 1, maxRows: 8 }}
        submitType="enter"
        ariaLabel="消息输入框"
        header={attachmentHeader}
        footer={footer}
        onChange={handleChange}
        onSubmit={handleSubmit}
        onStop={handleCancel}
      />
    </div>
  );
}
