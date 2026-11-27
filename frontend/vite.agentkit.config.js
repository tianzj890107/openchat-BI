import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {resolve} from "node:path";
import {fileURLToPath} from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

// AgentKit workbench build: one IIFE + one stylesheet into its own asset
// directory, so the Pro UI bundle in vendor/antd stays untouched (spec §2).
export default defineConfig({
  plugins: [react()],
  // Only the workbench bundle and its stylesheet belong in this asset folder;
  // the Pro UI public/ libraries must not be copied along with the build.
  publicDir: false,
  define: {"process.env.NODE_ENV": JSON.stringify("production")},
  build: {
    outDir: resolve(here, "../bi_agent/web/static/vendor/agentkit"),
    emptyOutDir: true,
    lib: {
      entry: resolve(here, "agentkit/main.jsx"),
      formats: ["iife"],
      name: "AgentkitWorkbench",
      fileName: () => "workbench-agentkit.js",
      cssFileName: "workbench-agentkit",
    },
  },
});
