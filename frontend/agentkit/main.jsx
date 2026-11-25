import React from "react";
import {createRoot} from "react-dom/client";

import App from "./App.jsx";
import {AGENTKIT_RUNTIME} from "./messageAdapter.js";
import "./agentkit-theme.css";

const host = document.getElementById("agentkit-root");
if (host) {
  host.setAttribute("aria-busy", "false");
  host.dataset.agentkitRuntime = AGENTKIT_RUNTIME;
  createRoot(host).render(<App version={host.dataset.appVersion} />);
}
