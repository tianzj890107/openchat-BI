import React, {useEffect, useState} from "react";
import {AuiIf, ComposerPrimitive} from "@assistant-ui/react";
import {ChevronDown} from "lucide-react";
import {loadModelConfig} from "../api.js";
import ReportControls, {AttachmentList, AttachmentPicker, ReportWizard} from "./ReportControls.jsx";
import {modelKey, ModelSettings} from "./Settings.jsx";

/**
 * AgentKit composer: assistant-ui's composer primitives own the input state,
 * Enter/Shift+Enter behaviour, and the send/stop pair driven by thread state.
 */
export default function Composer({busy, mode, sessionId, onSavePreferences, report, reportChanging, onAttachments,
  onUpload, onWithDb, onGenerate, onPrefillIfEmpty}) {
  const [config, setConfig] = useState(null);
  const [open, setOpen] = useState(false);
  const [attachmentDialog, setAttachmentDialog] = useState("");
  const [attachmentNotice, setAttachmentNotice] = useState("");
  const ready = Boolean(config?.data);
  useEffect(() => {
    if (ready) return undefined;
    const controller = new AbortController();
    loadModelConfig(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setConfig({data}); },
      (error) => { if (!controller.signal.aborted) setConfig({error: error.message}); },
    );
    return () => controller.abort();
  }, [open, ready]);
  const key = config?.data?.current?.model_key;
  const model = config?.data?.models?.find((item) => modelKey(item) === key);
  const label = model?.label || key || "模型";
  const shortLabel = label.split(" · ")[0].replace(/（环境配置）/g, "");

  return (
    <div className="ak-composer-dock">
    <ComposerPrimitive.Root className="ak-composer">
      <AttachmentList reports={report.active_reports || []} busy={busy}
        onRemove={async (id) => {
          setAttachmentNotice("");
          try { await onAttachments(report.active_reports.filter((file) => file.id !== id).map((file) => file.id)); }
          catch (error) { setAttachmentNotice(error.message); }
        }} />
      {reportChanging ? <p className="ak-attachment-notice" role="status">正在更新附件或报表配置…</p> : null}
      {attachmentNotice ? <p className="ak-attachment-notice" role="status">{attachmentNotice}</p> : null}
      <div className="ak-composer-entry">
        <ReportControls context={report} busy={busy} onUpload={onUpload} onWithDb={onWithDb}
          onClearContext={() => onAttachments([])}
          onOpenDialog={setAttachmentDialog} onNotice={setAttachmentNotice} onPrefillIfEmpty={onPrefillIfEmpty} />
        <ComposerPrimitive.Input
          className="ak-composer-input"
          rows={2}
          placeholder={mode === "report" ? "输入要分析的报表问题" : "描述你的经营问题，例如：PACK 未签单商机主要涉及哪些客户和产品部？"}
          aria-label="输入问题"
        />
      </div>
      <div className="ak-composer-actions">
        <button type="button" className="ak-model-select" aria-label={`模型设置：${label}`} aria-haspopup="dialog"
          title={label} onClick={() => setOpen(true)}>
          <span>{shortLabel}</span><ChevronDown size={13} aria-hidden="true" />
        </button>
        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel className="ak-stop">停止</ComposerPrimitive.Cancel>
        </AuiIf>
        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send className="ak-send">发送</ComposerPrimitive.Send>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
    {attachmentDialog === "recent" ? <AttachmentPicker active={report.active_reports || []}
      onChange={async (ids) => {
        await onAttachments(ids);
        if (ids.length) onPrefillIfEmpty("请分析上传的附件。");
      }} onClose={() => setAttachmentDialog("")} /> : null}
    {attachmentDialog === "generate" ? <ReportWizard onGenerate={onGenerate} onClose={() => setAttachmentDialog("")} /> : null}
    {open ? <ModelSettings config={config} onSaved={(data) => setConfig({data})} sessionId={sessionId} onSavePreferences={onSavePreferences}
      busy={busy} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
