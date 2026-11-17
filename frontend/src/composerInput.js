// Composer rules shared by the workbench and its root-cause embed mode.
//
// `takeComposerText` empties the box *before* any request starts, so the user
// sees the message move into the conversation immediately.  `isComposerSendKey`
// keeps plain Enter as the send key while Shift+Enter and IME composition keep
// their normal editing behaviour.

export function takeComposerText(input) {
  if (!input) return ""
  const text = String(input.value ?? "").trim()
  if (!text) return ""
  input.value = ""
  return text
}

export function isComposerSendKey(event) {
  if (!event || event.key !== "Enter" || event.shiftKey) return false
  if (event.isComposing || event.keyCode === 229 || event.which === 229) return false
  return true
}

// The root-cause dialog runs an ephemeral analysis session: closing it must not
// add a conversation to 最近 or write one through the general save path.
export function shouldPersistConversation({ embed } = {}) {
  return String(embed ?? "") !== "rootcause";
}
