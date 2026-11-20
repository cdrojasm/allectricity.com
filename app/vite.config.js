import { resolve } from "node:path";
import { defineConfig } from "vite";

// Two pages: index.html is the app (app.<domain>), landing.html the public landing (root domain).
// nginx picks one by Host; see nginx.conf and deploy/railway/nginx.conf.template.
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, "index.html"),
        landing: resolve(import.meta.dirname, "landing.html"),
      },
    },
  },
});
