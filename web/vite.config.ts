import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // ws: live voice (/api/voice/live). The Host header is kept, so the server's same-origin check passes.
  server: { proxy: { "/api": { target: "http://localhost:8000", ws: true } } },
});
