import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const target = env.VITE_API_BASE || "http://137.184.4.45:30080";
  const proxy = {
    "/sandboxes": { target, changeOrigin: true },
    "/health": { target, changeOrigin: true },
    "/auth": { target, changeOrigin: true },
  };
  return {
    server: { port: 5173, proxy },
    preview: { port: 5173, proxy },
  };
});
