import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/sandboxes": { target: "http://127.0.0.1", changeOrigin: true },
      "/health": { target: "http://127.0.0.1", changeOrigin: true },
    },
  },
  preview: {
    port: 5173,
    proxy: {
      "/sandboxes": { target: "http://127.0.0.1", changeOrigin: true },
      "/health": { target: "http://127.0.0.1", changeOrigin: true },
    },
  },
});
