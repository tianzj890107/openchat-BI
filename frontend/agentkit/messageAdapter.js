// Pure turn -> assistant-ui message projection.
//
// Kept free of @assistant-ui/react imports so it can be unit-tested in Node
// without booting the runtime package; runtime.js wires it into the provider.

export const AGENTKIT_RUNTIME = "agentkit-runtime:assistant-ui";

export function toThreadMessages(turns) {
  const messages = [];
  for (const turn of turns || []) {
    if (turn.user) {
      messages.push({
        id: `${turn.id}-user`,
        role: "user",
        content: [{type: "text", text: turn.user}],
        createdAt: new Date(),
      });
    }
    messages.push({
      id: `${turn.id}-assistant`,
      role: "assistant",
      content: [{type: "text", text: turn.assistant?.text || " "}],
      metadata: {
        custom: {
          tools: turn.assistant?.tools || [],
          turnStatus: turn.status || "idle",
          pendingChoice: Boolean(turn.status === "paused"),
        },
      },
      createdAt: new Date(),
    });
  }
  return messages;
}

/** The text a composer append carries; non-text parts (files, images) are ignored. */
export function textFromAppend(message) {
  const parts = Array.isArray(message?.content) ? message.content : [];
  return parts
    .filter((part) => part && part.type === "text")
    .map((part) => part.text || "")
    .join("")
    .trim();
}
