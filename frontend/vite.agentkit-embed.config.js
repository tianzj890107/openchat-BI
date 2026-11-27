import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {resolve} from "node:path";
import {fileURLToPath} from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

// 储小策嵌入式助手：复用 AgentKit 组件，单独输出一份 IIFE + 样式，
// 与分析工作台共用 static/vendor/agentkit/ 目录但互不覆盖。
export default defineConfig({
  plugins: [react()],
  publicDir: false,
  define: {"process.env.NODE_ENV": JSON.stringify("production")},
  build: {
    outDir: resolve(here, "../bi_agent/web/static/vendor/agentkit"),
    emptyOutDir: false,
    lib: {
      entry: resolve(here, "agentkit/embed-main.jsx"),
      formats: ["iife"],
      name: "ChuxiaoceAssistant",
      fileName: () => "workbench-agentkit-embed.js",
      cssFileName: "workbench-agentkit-embed",
    },
  },
});
