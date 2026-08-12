import { defineConfig, devices } from '@playwright/test'

/**
 * HakusAI Desktop Client — Playwright E2E 配置
 *
 * 目标：验证刷新后状态保留、资源不崩溃、所有入口可用且无控制台错误。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:1421',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Prefer system Google Chrome on dev machines; fall back to bundled Chromium in CI.
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:1421',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
})
