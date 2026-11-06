/**
 * Pure presentation adapters for the Pro UI workbench shell.
 *
 * The legacy runtime remains the single owner of requests, history and
 * business state. These helpers only normalize the small DOM state that the
 * React work surface mirrors, so they can be tested without a browser.
 */

export function composerActionState({ value = "", busy = false, disabled = false } = {}) {
  const text = String(value == null ? "" : value);
  return {
    text,
    canSubmit: !busy && !disabled && text.trim().length > 0,
    canCancel: !!busy,
    submitLabel: busy ? "停止" : "发送",
  };
}

export function normalizeComposerValue(value) {
  return String(value == null ? "" : value);
}

export function welcomePromptsFromHints(hints = []) {
  const seen = new Set();
  return (Array.isArray(hints) ? hints : [])
    .map((item) => normalizeComposerValue(item).trim())
    .filter((text) => {
      if (!text || seen.has(text)) return false;
      seen.add(text);
      return true;
    })
    .map((text, index) => ({
      key: `welcome-prompt-${index}`,
      label: text,
      description: "填入输入框，继续补充你的问题",
    }));
}

export function navigationActiveKey(view = "workspace", mode = "data") {
  const normalizedView = String(view || "workspace");
  if (normalizedView === "workspace") {
    return mode === "report" ? "report" : "data";
  }
  return normalizedView;
}

export function sidebarCollapsedFromPreference(savedValue, shellCollapsed = false) {
  if (savedValue === "1") return true;
  if (savedValue === "0") return false;
  return !!shellCollapsed;
}
