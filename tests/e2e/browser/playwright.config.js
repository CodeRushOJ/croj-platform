import { defineConfig } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const browserRoot = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(browserRoot, "../../..");
export default defineConfig({
  testDir: browserRoot,
  testMatch: "product.spec.js",
  timeout: 120_000,
  globalTimeout: 180_000,
  expect: {
    timeout: 15_000,
  },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir: path.join(
    repositoryRoot,
    "artifacts/product-e2e-browser/test-results",
  ),
  reporter: [
    ["line"],
    ["html", {
      outputFolder: path.join(
        repositoryRoot,
        "artifacts/product-e2e-browser/report",
      ),
      open: "never",
    }],
  ],
  use: {
    baseURL:
      process.env.CODERUSHOJ_E2E_BROWSER_BASE_URL
      || "http://coderushoj.local:8080",
    headless: true,
    locale: "zh-CN",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    launchOptions: {
      args: [
        "--host-resolver-rules=MAP coderushoj.local 127.0.0.1",
      ],
    },
  },
});
