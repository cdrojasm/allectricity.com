import { defineConfig } from "@playwright/test";

// E2E against the local docker stack (nginx on :3000) with the real agent and solver.
export default defineConfig({
  testDir: "./e2e",
  timeout: 45 * 60 * 1000,
  expect: { timeout: 30_000 },
  outputDir: "test-results/e2e-artifacts",
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000",
    viewport: { width: 1600, height: 1000 },
    trace: "retain-on-failure",
    video: "retain-on-failure",
    acceptDownloads: true,
  },
});
