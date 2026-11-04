/**
 * End-to-end tests of the five demo scenarios (Phase 9, D-49) in a real browser against the real API.
 * Prerequisite: the demo database — `cd backend && uv run python -m scripts.reset_demo && uv run python -m scripts.seed_demo`.
 * Run: `npm run e2e` — starts its own uvicorn (:8077) and Vite (:5177); never reuses a server already on those ports,
 * so another project's dev server cannot answer instead of RetailPilot.
 */
import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8077;
const WEB_PORT = 5177;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT} --loop app.core.db:selector_event_loop`,
      cwd: "../backend",
      url: `http://127.0.0.1:${API_PORT}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { RETAILPILOT_API: `http://127.0.0.1:${API_PORT}`, VITE_USE_MOCKS: "false" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
