import React from "react";
import {AuiIf, ComposerPrimitive} from "@assistant-ui/react";

/**
 * AgentKit composer: assistant-ui's composer primitives own the input state,
 * Enter/Shift+Enter behaviour, and the send/stop pair driven by thread state.
 */
export default function Composer() {
  return (
    <ComposerPrimitive.Root className="ak-composer">
      <ComposerPrimitive.Input
        className="ak-composer-input"
        rows={2}
        placeholder="描述你的经营问题，例如：PACK 未签单商机主要涉及哪些客户和产品部？"
        aria-label="输入问题"
      />
      <div className="ak-composer-actions">
        <span className="ak-composer-hint">Enter 发送 · Shift+Enter 换行</span>
        <AuiIf condition={(state) => state.thread.isRunning}>
          <ComposerPrimitive.Cancel className="ak-stop">停止</ComposerPrimitive.Cancel>
        </AuiIf>
        <AuiIf condition={(state) => !state.thread.isRunning}>
          <ComposerPrimitive.Send className="ak-send">发送</ComposerPrimitive.Send>
        </AuiIf>
      </div>
    </ComposerPrimitive.Root>
  );
}
