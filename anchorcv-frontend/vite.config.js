import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // Local backend for development testing.
        // Switch back to "http://178.104.48.216:8000" to test against production.
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
