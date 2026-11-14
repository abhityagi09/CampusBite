import { defineConfig } from "@playwright/test";

// E2E against the REAL stack: backend (docker compose, seeded) + Vite dev server.
// Uses the locally installed Google Chrome (no browser download needed).
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL || "http://localhost:5173", channel: "chrome", headless: true, trace: "retain-on-failure" },
  // E2E_BASE_URL=http://localhost:3000 tests the Docker build instead of the dev server.
  webServer: process.env.E2E_BASE_URL ? undefined : { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: true, timeout: 60_000 },
});
