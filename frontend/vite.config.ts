import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: [".."],
    },
    // API mode: forward /api to the FastAPI backend (uvicorn backend.api.main:app --port 8000).
    proxy: {
      "/api": process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
    },
  },
});
