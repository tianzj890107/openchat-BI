import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  // React's production bundle checks this expression. In Vite library mode
  // it is not injected automatically, so define it for a browser-only IIFE.
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: resolve(here, "../bi_agent/web/static/vendor/antd"),
    emptyOutDir: true,
    lib: {
      entry: resolve(here, "src/main.jsx"),
      formats: ["iife"],
      name: "OpenChatBIAntd",
      fileName: () => "workbench.js",
    },
  },
});
