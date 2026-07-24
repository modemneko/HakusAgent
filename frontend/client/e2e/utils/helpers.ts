/**
 * HakusAI E2E Test Helpers
 *
 * Shared utilities for Playwright tests including:
 * - Console error collection and filtering
 * - Page initialization helpers
 * - Common UI interaction patterns
 * - Network condition simulation
 */

import { type Page, type ConsoleMessage, type Locator, expect } from '@playwright/test'

// ============================================================================
// Console Error Monitoring
// ============================================================================

/**
 * 页面加载后常见的后端 404/连接错误，在测试环境无服务时属于预期行为，
 * 不应被判定为 UI 崩溃。
 */
export function isExpectedApiError(msg: ConsoleMessage): boolean {
  const text = msg.text()
  const expectedEndpoints = /\/(health|config|providers|sessions|version)\b/
  
  // In the test environment the Python backend is not running, so any
  // network failure against backend endpoints is expected.
  if (text.includes('Failed to load resource') && text.includes('404')) return true
  if (text.includes('Failed to fetch') && expectedEndpoints.test(text)) return true
  if (text.includes('status of 404') && expectedEndpoints.test(text)) return true
  // Session store logs backend fetch failures without the URL in the message;
  // treat these as expected when the sidecar is unavailable.
  if (text.includes('[session]') && text.includes('Failed to fetch')) return true
  // Settings provider loading errors when sidecar is unavailable
  if (text.includes('[settings]') && (text.includes('Failed to fetch') || text.includes('NetworkError'))) return true
  return false
}

/**
 * 收集页面控制台错误/警告，过滤掉预期的后端缺失错误。
 * 返回一个数组，包含收集到的非预期错误。
 */
export async function collectConsoleErrors(page: Page): Promise<string[]> {
  const errors: string[] = []
  
  page.on('console', (msg) => {
    const type = msg.type()
    if ((type === 'error' || type === 'warning') && !isExpectedApiError(msg)) {
      errors.push(`[${type}] ${msg.text()}`)
    }
  })
  
  page.on('pageerror', (err) => {
    errors.push(`[pageerror] ${err.message}`)
  })
  
  return errors
}

/**
 * 创建控制台错误监控器，支持在测试期间实时检查错误。
 * 返回一个对象，可以获取当前收集到的错误数量和内容。
 */
export function createConsoleMonitor(page: Page) {
  const errors: string[] = []
  let enabled = true

  const consoleHandler = (msg: ConsoleMessage) => {
    if (!enabled) return
    const type = msg.type()
    if ((type === 'error' || type === 'warning') && !isExpectedApiError(msg)) {
      errors.push(`[${type}] ${msg.text()}`)
    }
  }

  const pageErrorHandler = (err: Error) => {
    if (!enabled) return
    errors.push(`[pageerror] ${err.message}`)
  }

  page.on('console', consoleHandler)
  page.on('pageerror', pageErrorHandler)

  return {
    /** 获取所有收集到的错误 */
    getErrors(): string[] {
      return [...errors]
    },
    /** 获取错误数量 */
    getErrorCount(): number {
      return errors.length
    },
    /** 断言没有非预期错误 */
    async assertNoErrors() {
      expect(errors).toHaveLength(0)
    },
    /** 停止收集新错误 */
    disable() {
      enabled = false
    },
    /** 恢复收集错误 */
    enable() {
      enabled = true
    },
    /** 清空已收集的错误 */
    clear() {
      errors.length = 0
    },
    /** 清理监听器 */
    dispose() {
      page.off('console', consoleHandler)
      page.off('pageerror', pageErrorHandler)
    }
  }
}

// ============================================================================
// Page Initialization Helpers
// ============================================================================

/**
 * 初始化页面并等待基本 UI 元素加载完成
 */
export async function initializeApp(page: Page): Promise<void> {
  await page.goto('/')
  await page.waitForLoadState('networkidle')
  await page.waitForSelector('aside', { state: 'visible', timeout: 10000 })
  await page.waitForSelector('header', { state: 'visible', timeout: 10000 })
}

/**
 * 等待应用完全加载（包括侧边栏、顶部栏、输入框）
 */
export async function waitForAppReady(page: Page, timeout = 15000): Promise<void> {
  await Promise.all([
    page.waitForSelector('aside', { state: 'visible', timeout }),
    page.waitForSelector('header', { state: 'visible', timeout }),
    page.waitForSelector('textarea', { state: 'visible', timeout }),
  ])
}

// ============================================================================
// Sidebar Helpers
// ============================================================================

/**
 * 获取侧边栏新建会话按钮
 */
export function getNewChatButton(page: Page): Locator {
  return page.locator('aside button[title="New chat"]')
}

/**
 * 点击新建会话并等待会话创建完成
 */
export async function createNewSession(page: Page): Promise<string> {
  const sessionCountBefore = await page.locator('aside').locator('text=New Chat').count()
  
  await getNewChatButton(page).click()
  await expect(page.locator('aside').locator('text=New Chat').first()).toBeVisible({ timeout: 5000 })
  
  // 返回新建的会话标题用于验证
  return 'New Chat'
}

/**
 * 获取指定会话的操作菜单按钮
 */
export function getSessionMenuButton(page: Page, sessionTitle: string): Locator {
  const sessionItem = page.locator('aside').locator(`text=${sessionTitle}`).first()
    .locator('xpath=ancestor::*[contains(@class, "group")]')
  return sessionItem.locator('button[aria-label="更多操作"]')
}

// ============================================================================
// Settings Dialog Helpers
// ============================================================================

/**
 * 打开设置对话框
 */
export async function openSettingsDialog(page: Page): Promise<void> {
  await page.locator('header button[title="设置"]').click()
  await expect(page.locator('role=dialog')).toBeVisible({ timeout: 5000 })
}

/**
 * 关闭设置对话框
 */
export async function closeSettingsDialog(page: Page): Promise<void> {
  await page.keyboard.press('Escape')
  await expect(page.locator('role=dialog')).toHaveCount(0, { timeout: 5000 })
}

/**
 * 切换到指定的设置分类
 */
export async function switchSettingsCategory(page: Page, categoryLabel: string): Promise<void> {
  await page.locator(`nav button:has-text("${categoryLabel}")`).click()
  await expect(page.locator(`text=设置 · ${categoryLabel}`)).toBeVisible({ timeout: 3000 })
}

/**
 * 所有可用的设置分类标签
 */
export const SETTINGS_CATEGORIES = [
  '模型配置',
  '角色',
  '对话',
  '语音 TTS',
  '记忆',
  '工具与权限',
  '外观',
  '托盘与快捷键',
  'MCP 服务器',
  '微信',
  '连接',
  '高级',
  '关于与更新',
] as const

// ============================================================================
// Composer / Input Helpers
// ============================================================================

/**
 * 获取消息输入框
 */
export function getComposerTextarea(page: Page): Locator {
  return page.locator('textarea').first()
}

/**
 * 获取发送按钮
 */
export function getSendButton(page: Page): Locator {
  return page.locator('button[title="Send"]')
}

/**
 * 获取停止生成按钮
 */
export function getStopButton(page: Page): Locator {
  return page.locator('button[title="Stop"]')
}

/**
 * 输入并发送消息
 */
export async function sendMessage(page: Page, message: string): Promise<void> {
  const textarea = getComposerTextarea(page)
  await expect(textarea).toBeVisible()
  await textarea.fill(message)
  await getSendButton(page).click()
}

// ============================================================================
// TopBar Helpers
// ============================================================================

/**
 * 获取侧边栏切换按钮
 */
export function getSidebarToggleButton(page: Page): Locator {
  return page.locator('header button[title="切换侧栏"]')
}

/**
 * 获取侧边栏包装器元素
 */
export function getSidebarWrapper(page: Page): Locator {
  return page.locator('[data-testid="sidebar-wrapper"]')
}

/**
 * 切换侧边栏显示状态
 */
export async function toggleSidebar(page: Page): Promise<void> {
  await getSidebarToggleButton(page).click()
}

// ============================================================================
// Network Simulation Helpers
// ============================================================================

/**
 * 模拟网络离线状态
 * 注意：这需要使用 browser context 的 offline API
 */
export async function setOffline(page: Page): Promise<void> {
  const context = page.context()
  await context.setOffline(true)
}

/**
 * 恢复网络在线状态
 */
export async function setOnline(page: Page): Promise<void> {
  const context = page.context()
  await context.setOffline(false)
}

/**
 * 在离线状态下执行操作并验证 UI 不崩溃
 */
export async function executeWhileOffline<T>(
  page: Page,
  action: () => Promise<T>,
): Promise<{ result: T; uiResponsive: boolean }> {
  await setOffline(page)
  
  let uiResponsive = false
  try {
    // 验证页面仍然响应
    await page.waitForTimeout(100)
    const isResponsive = await page.evaluate(() => {
      return document.visibilityState === 'visible' && !document.hidden
    })
    uiResponsive = isResponsive
    
    const result = await action()
    
    return { result, uiResponsive }
  } finally {
    await setOnline(page)
  }
}

// ============================================================================
// Assertion Helpers
// ============================================================================

/**
 * 断言无控制台错误的便捷方法
 */
export async function assertNoConsoleErrors(errors: string[]): Promise<void> {
  expect(errors).toHaveLength(0)
}

/**
 * 断言元素可见且可交互
 */
export async function assertElementInteractive(locator: Locator): Promise<void> {
  await expect(locator).toBeVisible()
  await expect(locator).toBeEnabled()
}

/**
 * 安全地断言元素存在（不抛出异常）
 */
export async function safelyExpectVisible(locator: Locator, timeout = 3000): Promise<boolean> {
  try {
    await expect(locator).toBeVisible({ timeout })
    return true
  } catch {
    return false
  }
}
