import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(here, "../bi_agent/web/static/vendor/antd"),
    emptyOutDir: true,
    lib: {
      entry: resolve(here, "src/main.jsx"),
      formats: ["iife"],
      name: "OpenChatBIAntd",
      fileName: () => "sidebar.js",
    },
  },
});
