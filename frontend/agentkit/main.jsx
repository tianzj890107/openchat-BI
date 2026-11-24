import React from "react";
import {createRoot} from "react-dom/client";

import App from "./App.jsx";
import "./agentkit-theme.css";

const host = document.getElementById("agentkit-root");
if (host) {
  host.setAttribute("aria-busy", "false");
  createRoot(host).render(<App />);
}
