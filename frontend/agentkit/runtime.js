import {useMemo} from "react";
import {useExternalStoreRuntime} from "@assistant-ui/react";

import {toThreadMessages} from "./messageAdapter.js";

/**
 * assistant-ui runtime for the AgentKit workbench.
 *
 * The analysis state (state.js) stays authoritative: the runtime is a view of
 * the same turns, so composer send/cancel and "is running" follow the SSE turn
 * instead of a second message store.  Tool runs travel in message metadata and
 * are rendered by the local Thread component (AgentKit thread/tool-group
 * conventions).
 */
import {textFromAppend} from "./messageAdapter.js";

export {AGENTKIT_RUNTIME, textFromAppend, toThreadMessages} from "./messageAdapter.js";

export function useAgentkitRuntime({turns, running, onNew, onCancel}) {
  const messages = useMemo(() => toThreadMessages(turns), [turns]);
  return useExternalStoreRuntime({
    messages,
    isRunning: Boolean(running),
    onNew: async (message) => {
      const text = textFromAppend(message);
      if (text) await onNew(text);
    },
    onCancel: async () => {
      await onCancel?.();
    },
  });
}
