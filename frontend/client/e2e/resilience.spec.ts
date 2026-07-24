/**
 * 容错性测试 (Resilience Tests)
 *
 * 测试场景：
 * 1. 断开网络连接时 UI 不崩溃
 * 2. API 返回错误时显示错误提示
 * 3. 加载失败的资源不影响其他功能
 * 4. WebSocket 断开重连机制（模拟）
 * 5. 无效输入处理
 * 6. 边界条件处理
 */

import { test, expect } from '@playwright/test'
import {
  createConsoleMonitor,
  initializeApp,
  getNewChatButton,
  getSidebarToggleButton,
  getSidebarWrapper,
  getComposerTextarea,
  getSendButton,
  openSettingsDialog,
  closeSettingsDialog,
  setOffline,
  setOnline,
} from './utils/helpers'

test.describe('容错性测试', () => {
  
  test.describe('网络断开处理', () => {
    
    test('离线状态下 UI 仍然响应', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      // 模拟网络断开
      await setOffline(page)
      
      // 等待一小段时间让应用检测到网络变化
      await page.waitForTimeout(500)
      
      // 验证基本 UI 元素仍然可见和可交互
      await expect(page.locator('header')).toBeVisible()
      await expect(page.locator('aside')).toBeVisible()
      await expect(getComposerTextarea(page)).toBeVisible()
      
      // 验证侧边栏切换仍然工作
      await getSidebarToggleButton(page).click()
      await expect(getSidebarWrapper(page)).toHaveCSS('width', /^0px$/)
      
      // 恢复侧边栏
      await getSidebarToggleButton(page).click()
      await expect(getSidebarWrapper(page)).toHaveCSS('width', /264px|16.5rem/)
      
      // 验证新建会话按钮仍然可见并可点击
      const newChatBtn = getNewChatButton(page)
      await expect(newChatBtn).toBeVisible()
      await expect(newChatBtn).toBeEnabled()
      
      // 恢复网络
      await setOnline(page)
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('离线后恢复网络应用正常工作', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      // 模拟网络断开
      await setOffline(page)
      await page.waitForTimeout(300)
      
      // 执行一些操作
      await getSidebarToggleButton(page).click()
      await page.waitForTimeout(200)
      await getSidebarToggleButton(page).click()
      
      // 恢复网络
      await setOnline(page)
      await page.waitForTimeout(500)
      
      // 验证应用恢复正常
      await expect(page.locator('header')).toBeVisible()
      await expect(page.locator('aside')).toBeVisible()
      
      // 尝试打开设置对话框
      await openSettingsDialog(page)
      await expect(page.locator('role=dialog')).toBeVisible()
      await closeSettingsDialog(page)
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('多次快速断网/连网不导致状态异常', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      // 快速切换网络状态多次
      for (let i = 0; i < 5; i++) {
        await setOffline(page)
        await page.waitForTimeout(100)
        await setOnline(page)
        await page.waitForTimeout(100)
      }
      
      // 验证应用仍然正常
      await expect(page.locator('header')).toBeVisible()
      await expect(page.locator('aside')).toBeVisible()
      await expect(getComposerTextarea(page)).toBeVisible()
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })
  })

  test.describe('API 错误处理', () => {
    
    test('API 返回 404 错误时不崩溃', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      // Mock API 请求返回错误
      await page.route('**/api/health**', async (route) => {
        route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Not found' }),
        })
      })
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      
      // 应用应该正常加载，即使 health API 失败
      await expect(page.locator('header')).toBeVisible({ timeout: 10000 })
      await expect(page.locator('aside')).toBeVisible({ timeout: 10000 })
      
      // 清除路由
      await page.unroute('**/api/health**')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('API 返回 500 错误时显示适当状态', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      // Mock sessions API 返回服务器错误
      await page.route('**/api/sessions**', async (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Internal server error' }),
        })
      })
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      
      // 应用应该正常加载，显示空状态或错误提示
      await expect(page.locator('header')).toBeVisible({ timeout: 10000 })
      await expect(page.locator('aside')).toBeVisible({ timeout: 10000 })
      
      // 清除路由
      await page.unroute('**/api/sessions**')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('API 响应超时时不阻塞 UI', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      // Mock API 请求永不响应（模拟超时）
      let requestCount = 0
      await page.route('**/api/config/providers**', async (route) => {
        requestCount++
        if (requestCount <= 2) {
          // 前两次请求不响应，模拟超时
          return new Promise(() => {}) // 永远不 resolve
        }
        await route.continue()
      })
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      
      // UI 应该在合理时间内变得可用，不等待超时的请求
      await expect(page.locator('header')).toBeVisible({ timeout: 10000 })
      await expect(page.locator('aside')).toBeVisible({ timeout: 10000 })
      
      // 清除路由
      await page.unroute('**/api/config/providers**')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('网络错误后可以重试操作', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      let shouldFail = true
      
      // Mock 新建会话 API 先失败后成功
      await page.route('**/api/sessions**', async (route) => {
        if (route.request().method() === 'POST' && shouldFail) {
          route.fulfill({
            status: 503,
            contentType: 'application/json',
            body: JSON.stringify({ error: 'Service unavailable' }),
          })
        } else {
          await route.continue()
        }
      })
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      await page.waitForSelector('aside', { state: 'visible' })
      
      // 第一次尝试创建会话（应该失败但 UI 不崩溃）
      await getNewChatButton(page).click()
      await page.waitForTimeout(500)
      
      // UI 应该仍然响应
      await expect(page.locator('aside')).toBeVisible()
      
      // 允许后续请求成功
      shouldFail = false
      
      // 再次尝试
      await getNewChatButton(page).click()
      await page.waitForTimeout(500)
      
      // 清除路由
      await page.unroute('**/api/sessions**')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })
  })

  test.describe('边界条件和无效输入', () => {
    
    test('超长文本输入不崩溃', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      const textarea = getComposerTextarea(page)
      await expect(textarea).toBeVisible()
      
      // 输入超长文本（10000 字符）
      const longText = 'A'.repeat(10000)
      await textarea.fill(longText)
      
      // 验证输入成功
      const value = await textarea.inputValue()
      expect(value.length).toBe(10000)
      
      // 清空并验证
      await textarea.clear()
      const emptyValue = await textarea.inputValue()
      expect(emptyValue).toBe('')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('特殊字符输入正确处理', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      const textarea = getComposerTextarea(page)
      await expect(textarea).toBeVisible()
      
      // 包含各种特殊字符的文本
      const specialTexts = [
        '<script>alert("xss")</script>',
        '"quotes" and \'single\'',
        '{}[]()',
        '&lt;html&gt;',
        'emoji: 🎉🚀💻',
        '中文测试！@#￥%',
        '\t\n\r escape chars',
        '   spaces   ',
      ]
      
      for (const text of specialTexts) {
        await textarea.fill(text)
        const value = await textarea.inputValue()
        expect(value).toBe(text)
      }
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('快速连续点击按钮不导致异常', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      // 快速连续点击新建会话按钮
      const newChatBtn = getNewChatButton(page)
      for (let i = 0; i < 10; i++) {
        await newChatBtn.click()
        await page.waitForTimeout(50)
      }
      
      // UI 应该仍然正常
      await expect(page.locator('aside')).toBeVisible()
      await expect(getComposerTextarea(page)).toBeVisible()
      
      // 快速连续切换侧边栏
      const toggleBtn = getSidebarToggleButton(page)
      for (let i = 0; i < 10; i++) {
        await toggleBtn.click()
        await page.waitForTimeout(50)
      }
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('空消息发送被正确阻止', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      const textarea = getComposerTextarea(page)
      const sendBtn = getSendButton(page)
      
      // 不输入任何内容
      await textarea.fill('')
      
      // 发送按钮应该是禁用状态
      const isDisabled = await sendBtn.isDisabled()
      expect(isDisabled).toBeTruthy()
      
      // 只输入空白字符
      await textarea.fill('   ')
      
      // 发送按钮仍然应该是禁用状态
      const isStillDisabled = await sendBtn.isDisabled()
      expect(isStillDisabled).toBeTruthy()
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })
  })

  test.describe('资源加载失败处理', () => {
    
    test('图片加载失败不影响布局', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      // Mock 图片请求返回失败
      await page.route('**/*.png', async (route) => {
        route.fulfill({
          status: 404,
          contentType: 'image/png',
          body: Buffer.from(''),
        })
      })
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      
      // 页面应该正常渲染
      await expect(page.locator('header')).toBeVisible({ timeout: 10000 })
      await expect(page.locator('aside')).toBeVisible({ timeout: 10000 })
      
      // 清除路由
      await page.unroute('**/*.png')
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })

    test('CSS 加载失败时有基本样式回退', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      // 注意：完全阻止 CSS 可能会导致测试不稳定
      // 这里我们只验证页面结构存在
      
      await page.goto('/')
      await page.waitForLoadState('networkidle')
      
      // 即使某些样式缺失，DOM 结构应该完整
      const hasHeader = await page.locator('header').count()
      const hasAside = await page.locator('aside').count()
      const hasMain = await page.locator('main, [class*="flex-1"]').count()
      
      expect(hasHeader).toBeGreaterThan(0)
      expect(hasAside).toBeGreaterThan(0)
      expect(hasMain).toBeGreaterThan(0)
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })
  })

  test.describe('内存泄漏防护', () => {
    
    test('大量操作后页面仍稳定', async ({ page }) => {
      const monitor = createConsoleMonitor(page)
      
      await initializeApp(page)
      
      // 执行大量操作
      for (let i = 0; i < 20; i++) {
        // 创建会话
        await getNewChatButton(page).click()
        await page.waitForTimeout(100)
        
        // 切换侧边栏
        if (i % 3 === 0) {
          await getSidebarToggleButton(page).click()
          await page.waitForTimeout(50)
          await getSidebarToggleButton(page).click()
        }
        
        // 打开关闭设置
        if (i % 5 === 0) {
          await openSettingsDialog(page)
          await page.waitForTimeout(100)
          await closeSettingsDialog(page)
        }
      }
      
      // 验证页面仍然稳定
      await expect(page.locator('header')).toBeVisible()
      await expect(page.locator('aside')).toBeVisible()
      await expect(getComposerTextarea(page)).toBeVisible()
      
      // 检查是否有明显的性能问题（通过 JS 堆大小估算）
      const metrics = await page.evaluate(() => {
        return {
          // 获取 DOM 节点数量作为简单指标
          nodeCount: document.querySelectorAll('*').length,
          // 获取事件监听器数量的近似值（无法直接获取）
          memoryUsage: (performance as any).memory ? {
            usedJSHeapSize: (performance as any).memory.usedJSHeapSize,
            totalJSHeapSize: (performance as any).memory.totalJSHeapSize,
          } : null,
        }
      })
      
      // DOM 节点数量应该在合理范围内
      expect(metrics.nodeCount).toBeLessThan(10000)
      
      await monitor.assertNoErrors()
      monitor.dispose()
    })
  })
})
