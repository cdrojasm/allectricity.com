import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Variables desde el entorno; si existe app/.env.smoke-ui (solo local) se cargan sin pisar las ya definidas.
const envFile = path.resolve(import.meta.dirname, "../.env.smoke-ui");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2];
  }
}

export default defineConfig({
  testDir: "./specs",
  globalSetup: "./global-setup.js",
  workers: 1, // un solo navegador a la vez: la prueba toca datos compartidos y en prod no debe haber concurrencia
  retries: 0, // un reintento podría crear objetos duplicados
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["json", { outputFile: "../test-results/smoke-ui/report.json" }]],
  outputDir: "../test-results/smoke-ui/artifacts",
  use: {
    baseURL: process.env.SMOKE_BASE_URL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 20_000,
  },
});
