import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

/**
 * Builds straight into Django's static tree.
 *
 * There is no Vite dev server in this setup. Django serves every page,
 * including the SPA shell, so running two servers would mean two origins and
 * the httpOnly auth cookie only belongs to one of them. `npm run dev` instead
 * runs `vite build --watch`, which rewrites static/app/ on save while Django
 * keeps serving it from a single origin. Slightly slower than HMR, and it
 * keeps auth working exactly as it does in production.
 *
 * manifest.json is emitted so the Django shell view can resolve hashed
 * filenames instead of hard-coding them.
 */
export default defineConfig({
  plugins: [react()],
  base: "/static/app/",
  build: {
    outDir: resolve(__dirname, "../static/app"),
    emptyOutDir: true,
    manifest: "manifest.json",
    rollupOptions: {
      input: resolve(__dirname, "src/main.tsx"),
    },
    // Mid-range Android on 4G is a large share of this market; keep the
    // entry small and let routes split themselves.
    target: "es2020",
    sourcemap: false,
  },
  resolve: {
    alias: { "@": resolve(__dirname, "src") },
  },
});
