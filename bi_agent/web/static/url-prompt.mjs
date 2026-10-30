// Reuse the normal chat submission after the workbench has initialized.
export async function submitPromptFromUrl({ location, history, ready, submit }) {
  await ready;
  const url = new URL(location.href);
  const prompt = (url.searchParams.get("prompt") || "").trim();
  if (!prompt) return false;

  // Consume the parameter before sending so refresh cannot repeat the turn.
  // Keep layout/theme parameters, the hash, and the current history entry.
  url.searchParams.delete("prompt");
  history.replaceState(history.state, "", url.href);
  await submit(prompt);
  return true;
}

export function waitForWorkbench(window, document) {
  return new Promise((resolve) => {
    const check = () => {
      const input = document.getElementById("chat-input");
      const button = document.getElementById("btn-send");
      // The runtime emits this layout event after binding the composer.
      // The dataset also covers modules loaded after that event has fired.
      if (!document.body?.dataset.layout || !input || !button) return;
      window.removeEventListener("bi-viewport-mode", check);
      resolve({ input, button });
    };
    window.addEventListener("bi-viewport-mode", check);
    check();
  });
}

export async function bootUrlPrompt(window, document) {
  if (!(new URL(window.location.href).searchParams.get("prompt") || "").trim()) return false;
  const composer = waitForWorkbench(window, document);
  return submitPromptFromUrl({
    location: window.location,
    history: window.history,
    ready: composer,
    submit: async (prompt) => {
      const { input, button } = await composer;
      input.value = prompt;
      input.dispatchEvent(new window.Event("input", { bubbles: true }));
      button.click();
    },
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  void bootUrlPrompt(window, document).catch((error) => console.error("URL prompt submission failed", error));
}
