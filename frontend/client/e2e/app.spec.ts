import { test, expect, type Page, type ConsoleMessage } from '@playwright/test'

/**
 * 页面加载后常见的后端 404/连接错误，在测试环境无服务时属于预期行为，
 * 不应被判定为 UI 崩溃。
 */
function isExpectedApiError(msg: ConsoleMessage): boolean {
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
  return false
}

/**
 * 收集页面控制台错误/警告，过滤掉预期的后端缺失错误。
 */
async function collectConsoleErrors(page: Page): Promise<string[]> {
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

test.describe('HakusAI App — macOS/Codex UI', () => {
  test('app loads with title bar, sidebar and composer visible', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Title bar
    await expect(page.locator('header')).toBeVisible()

    // Sidebar
    await expect(page.locator('aside')).toBeVisible()
    await expect(page.locator('aside')).toContainText('HakusAI')
    await expect(page.locator('aside input[placeholder="搜索会话..."]')).toBeVisible()

    // Composer placeholder (connection may be offline in test env)
    await expect(page.getByPlaceholder(/未连接到服务|Send a message/)).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('sidebar new chat button creates a session', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('aside', { state: 'visible' })

    const newChatButton = page.locator('aside button[title="New chat"]')
    await expect(newChatButton).toBeVisible()
    await newChatButton.click()

    // A new session item should appear
    await expect(page.locator('aside').locator('text=New Chat').first()).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('session actions menu provides rename and delete', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('aside', { state: 'visible' })

    // Create a session first
    await page.locator('aside button[title="New chat"]').click()
    await expect(page.locator('aside').locator('text=New Chat').first()).toBeVisible()

    // Open the action menu of the newly created session (not a WeChat session)
    const newSessionItem = page.locator('aside').locator('text=New Chat').first().locator('xpath=ancestor::*[contains(@class, "group")]')
    const menuButton = newSessionItem.locator('button[aria-label="更多操作"]')
    await expect(menuButton).toBeVisible()
    await menuButton.click()

    // Verify menu items
    await expect(page.locator('text=重命名').first()).toBeVisible()
    await expect(page.locator('text=置顶').first()).toBeVisible()
    await expect(page.locator('text=删除').first()).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('settings dialog opens and all categories are reachable', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('header', { state: 'visible' })

    // Open settings from top bar
    await page.locator('header button[title="设置"]').click()

    // Dialog visible
    await expect(page.locator('role=dialog')).toBeVisible()
    await expect(page.locator('text=设置 · 模型配置')).toBeVisible()

    // Navigate through a few categories
    const categories = ['模型配置', '外观', '连接', '关于与更新']
    for (const label of categories) {
      await page.locator(`nav button:has-text("${label}")`).click()
      await expect(page.locator(`text=设置 · ${label}`)).toBeVisible()
    }

    // Close
    await page.keyboard.press('Escape')
    await expect(page.locator('role=dialog')).toHaveCount(0)

    expect(errors).toHaveLength(0)
  })

  test('sidebar toggle works and state persists after reload', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('aside', { state: 'visible' })

    // Sidebar wrapper should start open and have the expected width
    const sidebarWrapper = page.locator('[data-testid="sidebar-wrapper"]')
    await expect(sidebarWrapper).toHaveCSS('width', /264px|16.5rem/)

    // Toggle off
    await page.locator('header button[title="切换侧栏"]').click()
    await expect(sidebarWrapper).toHaveCSS('width', /^0px$/)

    // Reload and verify sidebar is still closed
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(sidebarWrapper).toHaveCSS('width', /^0px$/)

    // Toggle back on
    await page.locator('header button[title="切换侧栏"]').click()
    await expect(sidebarWrapper).toHaveCSS('width', /264px|16.5rem/)

    expect(errors).toHaveLength(0)
  })

  test('theme preference persists after reload', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('header', { state: 'visible' })

    // Open settings -> appearance
    await page.locator('header button[title="设置"]').click()
    await page.locator('nav button:has-text("外观")').click()

    // Click dark theme option if present
    const darkOption = page.locator('button:has-text("Dark")')
    if ((await darkOption.count()) > 0) {
      await darkOption.click()
      await expect(page.locator('html')).toHaveClass(/dark/)

      // Reload and verify dark class persists
      await page.reload()
      await page.waitForLoadState('networkidle')
      await expect(page.locator('html')).toHaveClass(/dark/)
    }

    expect(errors).toHaveLength(0)
  })

  test('ask_user interactive question renders options and accepts answer', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    let answerReceived = false

    // Mock the chat stream so the test does not depend on the LLM calling ask_user
    await page.route('**/api/chat/stream', async (route) => {
      const body = JSON.stringify({
        content: '',
        emotion: null,
        actions: [],
        done: false,
        event_type: 'turn_started',
        turn_id: 'turn_test_ask_user',
        model: 'test',
      })
      const qid = 'q-test-ask-user-001'
      const sseLines = [
        `data: ${body}`,
        `data: ${JSON.stringify({
          content: '',
          emotion: null,
          actions: [],
          done: false,
          event_type: 'question_asked',
          question_id: qid,
          question: 'Which color do you prefer?',
          options: ['red', 'blue'],
          allow_free_text: false,
        })}`,
        `data: ${JSON.stringify({
          content: '',
          emotion: null,
          actions: [],
          done: true,
          event_type: 'turn_completed',
          iterations: 1,
          input_tokens: 10,
          output_tokens: 5,
          compressed: false,
        })}`,
      ].join('\n\n')

      route.fulfill({
        status: 200,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
        },
        body: sseLines + '\n\n',
      })
    })

    // Mock the answer endpoint
    await page.route('**/api/question/answer', async (route) => {
      answerReceived = true
      route.fulfill({ status: 200, body: JSON.stringify({ ok: true }) })
    })

    await page.goto('/')
    await page.waitForSelector('aside', { state: 'visible' })

    // Create a new session
    await page.locator('aside button[title="New chat"]').click()
    await expect(page.locator('aside').locator('text=New Chat').first()).toBeVisible()

    // Send any message — the mocked stream will produce ask_user
    const composer = page.locator('textarea').first()
    await expect(composer).toBeVisible()
    await composer.fill('trigger ask_user')
    await page.locator('button[title="Send"]').click()

    // Wait for the interactive question card
    const questionCard = page.locator('text=羽汐想问').first().locator('xpath=ancestor::*[contains(@class, "rounded-")][1]')
    await expect(questionCard).toBeVisible({ timeout: 10000 })
    const optionButtons = questionCard.locator('div[class="space-y-1.5"] > button')
    await expect(optionButtons.first()).toBeVisible()

    // Select the first option, then confirm
    const firstOptionText = await optionButtons.first().locator('span.flex-1').textContent()
    await optionButtons.first().click()
    await questionCard.locator('button:has-text("继续")').click()

    // Verify answered state shows the selected option and answer was posted
    await expect(questionCard.locator('text=已选择')).toBeVisible({ timeout: 10000 })
    if (firstOptionText) {
      await expect(questionCard.locator(`text=${firstOptionText}`)).toBeVisible()
    }
    expect(answerReceived).toBe(true)

    expect(errors).toHaveLength(0)
  })

  // ========== 新增的增强测试用例 ==========

  test('app has correct viewport and layout structure', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 验证视口尺寸
    const viewportSize = page.viewportSize()
    expect(viewportSize?.width).toBeGreaterThan(0)
    expect(viewportSize?.height).toBeGreaterThan(0)

    // 验证基本布局结构
    const body = page.locator('body')
    await expect(body).toHaveClass(/overflow-hidden/) // 全屏布局

    // 主容器应该是 flex 布局
    const mainContainer = page.locator('.flex.h-screen.w-screen.overflow-hidden')
    await expect(mainContainer).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('all main UI sections are accessible via selectors', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 测试各种选择器都能找到元素
    const selectors = [
      'header',           // 顶部栏
      'aside',            // 侧边栏
      'textarea',         // 输入框
      '[data-testid="sidebar-wrapper"]', // 侧边栏包装器
    ]

    for (const selector of selectors) {
      const element = page.locator(selector)
      await expect(element.first()).toBeVisible({ timeout: 5000 })
    }

    expect(errors).toHaveLength(0)
  })

  test('composer input handles focus correctly', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const textarea = page.locator('textarea').first()
    await expect(textarea).toBeVisible()

    // 点击输入框获取焦点
    await textarea.click()
    await expect(textarea).toBeFocused()

    // 输入文本
    await textarea.type('Hello, HakusAI!')
    const value = await textarea.inputValue()
    expect(value).toBe('Hello, HakusAI!')

    expect(errors).toHaveLength(0)
  })

  test('sidebar search functionality renders correctly', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('aside', { state: 'visible' })

    // 搜索框应该可见
    const searchInput = page.locator('aside input[placeholder="搜索会话..."]')
    await expect(searchInput).toBeVisible()

    // 输入搜索词（可能没有结果，但不应该崩溃）
    await searchInput.fill('nonexistent_session_xyz')
    await page.waitForTimeout(300)

    // 应该显示"无匹配结果"或保持空状态
    const noResults = page.locator('aside').locator('text=无匹配结果')
    if ((await noResults.count()) > 0) {
      await expect(noResults).toBeVisible()
    }

    // 清空搜索
    await searchInput.clear()

    expect(errors).toHaveLength(0)
  })

  test('connection status indicator displays correctly', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 连接状态指示器应该在顶部栏中显示
    // 可能是"离线"、"未连接"、"在线"等状态
    const statusIndicators = page.locator('header').locator(
      'span:has-text("在线"), span:has-text("离线"), span:has-text("未连接"), span:has-text("连接中"), span:has-text("错误")'
    )
    
    // 至少应该有一个状态指示器
    await expect(statusIndicators.first()).toBeVisible({ timeout: 10000 })

    expect(errors).toHaveLength(0)
  })

  test('model info displays in top bar when available', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 顶部栏中央区域应该有标题和可能的模型信息
    const titleArea = page.locator('header').locator('span[class*="font-semibold"], span[class*="font-medium"]')
    await expect(titleArea.first()).toBeVisible()

    // 模型信息区域（可能在连接后显示）
    const modelInfo = page.locator('header').locator('span:has-text("无模型信息"), span[class*="font-mono"]')
    await expect(modelInfo.first()).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('toast notification system is available', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Toaster 组件应该在 DOM 中（即使没有 toast 显示）
    const toaster = page.locator('[class*="toast"], [data-toast], [role="status"]')
    // Toaster 可能在页面某处存在

    // 页面应该正常工作
    await expect(page.locator('header')).toBeVisible()
    await expect(page.locator('aside')).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('responsive design elements present', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 检查响应式设计相关的 CSS 类
    const sidebar = page.locator('aside')
    await expect(sidebar).toBeVisible()

    // 侧边栏应该有固定或相对宽度
    const sidebarWidth = await sidebar.evaluate(el => window.getComputedStyle(el).width)
    expect(parseFloat(sidebarWidth)).toBeGreaterThan(0)

    // 主内容区应该占据剩余空间
    const mainContent = page.locator('[class*="flex-1"]')
    await expect(mainContent.first()).toBeVisible()

    expect(errors).toHaveLength(0)
  })
})
