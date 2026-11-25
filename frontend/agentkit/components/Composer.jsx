import React, {useEffect, useState} from "react";
import {AuiIf, ComposerPrimitive} from "@assistant-ui/react";
import {ChevronDown} from "lucide-react";
import {loadModelConfig} from "../api.js";
import {modelKey, ModelSettings} from "./Settings.jsx";

/**
 * AgentKit composer: assistant-ui's composer primitives own the input state,
 * Enter/Shift+Enter behaviour, and the send/stop pair driven by thread state.
 */
export default function Composer({busy}) {
  const [config, setConfig] = useState(null);
  const [open, setOpen] = useState(false);
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
      <ComposerPrimitive.Input
        className="ak-composer-input"
        rows={2}
        placeholder="描述你的经营问题，例如：PACK 未签单商机主要涉及哪些客户和产品部？"
        aria-label="输入问题"
      />
      <div className="ak-composer-actions">
        <button type="button" className="ak-model-select" aria-label={`模型设置：${label}`} aria-haspopup="dialog"
          title={label} onClick={() => setOpen(true)}>
          <span>{shortLabel}</span><ChevronDown size={13} aria-hidden="true" />
        </button>
        <span className="ak-composer-hint">Enter 发送 · Shift+Enter 换行</span>
        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel className="ak-stop">停止</ComposerPrimitive.Cancel>
        </AuiIf>
        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send className="ak-send">发送</ComposerPrimitive.Send>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
    {open ? <ModelSettings config={config} onSaved={(data) => setConfig({data})}
      busy={busy} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
