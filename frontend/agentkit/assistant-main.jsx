import React from "react";
import {createRoot} from "react-dom/client";

import App from "./App.jsx";
import {installAssistantFetch} from "./assistantFetch.js";
import {AGENTKIT_RUNTIME} from "./messageAdapter.js";
import "./agentkit-theme.css";

const host = document.getElementById("agentkit-root");
if (host && /a360=assistant/.test(window.location.search)) {
  installAssistantFetch(window);
  host.setAttribute("aria-busy", "false");
  host.dataset.agentkitRuntime = AGENTKIT_RUNTIME;
  host.dataset.a360 = "assistant";
  createRoot(host).render(<App version={host.dataset.appVersion} assistant />);
}
