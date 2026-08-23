import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  // Vite inlines env at BUILD time. Without this guard a production build
  // with VITE_API_BASE_URL unset silently ships the localhost fallback in
  // src/api/client.ts, and every request from a visitor's browser targets
  // their own machine — the worst possible failure mode for a public demo,
  // because it looks like a backend outage rather than a config mistake.
  if (mode === "production" && !env.VITE_API_BASE_URL) {
    throw new Error(
      "VITE_API_BASE_URL is required for a production build.\n" +
        "Set it to the public API origin, e.g. https://orchestrel-api.onrender.com\n" +
        "(On Render: set it on the static site's Environment tab.)",
    );
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(import.meta.dirname, "./src"),
      },
    },
    server: {
      port: 5173,
    },
  };
});
