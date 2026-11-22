import { resolve } from "node:path";
import { defineConfig } from "vite";

// Three pages: index.html is the app (app.<domain>), landing.html the public landing (root domain) and
// paginas.html the public text pages: /ayuda, /terminos and /privacidad on both hosts.
// nginx picks one by Host; see nginx.conf and deploy/railway/nginx.conf.template.
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(import.meta.dirname, "index.html"),
        landing: resolve(import.meta.dirname, "landing.html"),
        paginas: resolve(import.meta.dirname, "paginas.html"),
      },
    },
  },
});
