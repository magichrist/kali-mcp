import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
  build: {
    /* Production output goes straight into the Studio web dir so the existing
       Starlette StaticFiles mount (src/kali_mcp/studio/web) serves it at /studio
       (main-server mode) and on the optional dedicated STUDIO_PORT. */
    outDir: path.resolve(__dirname, "../src/kali_mcp/studio/web"),
    emptyOutDir: true,
    sourcemap: true,
  },
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8399",
    },
  },
});
