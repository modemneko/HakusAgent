import { defineConfig, devices } from '@playwright/test'

/**
 * HakusAI Desktop Client — Playwright E2E 配置
 *
 * 目标：验证刷新后状态保留、资源不崩溃、所有入口可用且无控制台错误。
 *
 * 测试文件结构：
 * - e2e/app.spec.ts           主应用测试（基本 UI 和功能）
 * - e2e/persistence.spec.ts   状态持久化测试
 * - e2e/resilience.spec.ts    容错性测试
 * - e2e/accessibility.spec.ts 所有入口功能测试
 * - e2e/utils/helpers.ts      测试工具函数
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['html', { open: 'never' }], ['list']],
  
  // 全局超时配置
  timeout: 30_000,            // 单个测试用例超时 30 秒
  expect: {
    timeout: 10_000,          // 断言超时 10 秒
  },
  
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:1421',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Prefer system Google Chrome on dev machines; fall back to bundled Chromium in CI.
    channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome',
    // 浏览器上下文配置
    actionTimeout: 10_000,     // 操作超时 10 秒
    navigationTimeout: 30_000, // 导航超时 30 秒
  },
  
  projects: [
    {
      name: 'chromium',
      use: { 
        ...devices['Desktop Chrome'],
        // 覆盖默认视口大小以匹配应用设计
        viewport: { width: 1280, height: 800 },
      },
    },
  ],
  
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:1421',
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
  },
})
