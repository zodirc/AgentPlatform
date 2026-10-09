import path from "node:path";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    headers: {
      "Content-Security-Policy":
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws: wss:; font-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'",
    },
    fs: {
      allow: [
        path.resolve(__dirname),
        path.resolve(__dirname, "../../packages/contracts/plan_suggest"),
      ],
    },
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
