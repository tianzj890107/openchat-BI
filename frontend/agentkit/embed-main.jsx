import React from "react";
import {createRoot} from "react-dom/client";

import EmbedApp from "./embed.jsx";
import "./agentkit-theme.css";

const host = document.getElementById("chuxiaoce-root");
if (host && /a360=assistant/.test(window.location.search)) {
  host.setAttribute("aria-busy", "false");
  host.dataset.a360 = "assistant";
  createRoot(host).render(<EmbedApp version={host.dataset.appVersion} />);
}
