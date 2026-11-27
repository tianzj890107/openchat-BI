import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {resolve} from "node:path";
import {fileURLToPath} from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

// 储小策复用完整 AgentKit 工作台；独立构建到 vendor/agentkit，资源带版本查询串。
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  define: {"process.env.NODE_ENV": JSON.stringify("production")},
  build: {
    outDir: resolve(here, "../bi_agent/web/static/vendor/agentkit"),
    emptyOutDir: false,
    lib: {
      entry: resolve(here, "agentkit/assistant-main.jsx"),
      formats: ["iife"],
      name: "ChuxiaoceAssistant",
      fileName: () => "workbench-agentkit.js",
      cssFileName: "workbench-agentkit",
    },
  },
});
