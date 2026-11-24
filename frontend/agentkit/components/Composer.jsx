import React, {useEffect, useRef, useState} from "react";

/**
 * Composer: Enter sends, Shift+Enter and IME composition keep editing.
 * While a turn streams the send button is replaced by stop (spec §2, §4.1).
 */
export default function Composer({status, onSend, onStop}) {
  const [text, setText] = useState("");
  const inputRef = useRef(null);
  const busy = status === "streaming";

  useEffect(() => {
    if (!busy) inputRef.current?.focus();
  }, [busy]);

  const submit = () => {
    const value = text.trim();
    if (!value || busy) return;
    setText("");
    onSend(value);
  };

  const handleKeyDown = (event) => {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    submit();
  };

  return (
    <div className="ak-composer">
      <textarea
        ref={inputRef}
        className="ak-composer-input"
        rows={2}
        value={text}
        placeholder="描述你的经营问题，例如：PACK 未签单商机主要涉及哪些客户和产品部？"
        aria-label="输入问题"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="ak-composer-actions">
        <span className="ak-composer-hint">Enter 发送 · Shift+Enter 换行</span>
        {busy ? (
          <button type="button" className="ak-stop" onClick={onStop}>
            停止
          </button>
        ) : (
          <button type="button" className="ak-send" onClick={submit} disabled={!text.trim()}>
            发送
          </button>
        )}
      </div>
    </div>
  );
}
