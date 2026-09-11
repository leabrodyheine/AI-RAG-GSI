import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api to the FastAPI app (orswater.web:app, run separately with
// uvicorn on :8000) so the browser only ever talks to one origin -- no CORS needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
