import { test, expect, type Page, type ConsoleMessage } from '@playwright/test'

/**
 * 页面加载后常见的后端 404/连接错误，在测试环境无服务时属于预期行为，
 * 不应被判定为 UI 崩溃。
 */
function isExpectedApiError(msg: ConsoleMessage): boolean {
  const text = msg.text()
  const expectedEndpoints = /\/(health|config|providers|sessions|version|mcp)\b/
  // In the test environment the Python backend is not running, so any
  // network failure against backend endpoints is expected.
  if (text.includes('Failed to load resource') && text.includes('404')) return true
  if (text.includes('Failed to fetch') && expectedEndpoints.test(text)) return true
  if (text.includes('status of 404') && expectedEndpoints.test(text)) return true
  // ERR_CONNECTION_REFUSED — backend not running in test env
  if (text.includes('ERR_CONNECTION_REFUSED')) return true
  // Session store logs backend fetch failures without the URL in the message;
  // treat these as expected when the sidecar is unavailable.
  if (text.includes('[session]') && text.includes('Failed to fetch')) return true
  // ModelPanel / provider meta fetch failures when sidecar is offline
  if (text.includes('[ModelPanel]') && text.includes('Failed to fetch')) return true
  if (text.includes('getProvidersMeta failed')) return true
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
    // 后端未运行时的 fetch 失败属于预期行为
    if (err.message === 'Failed to fetch') return
    errors.push(`[pageerror] ${err.message}`)
  })
  return errors
}

test.describe('HakusAI App', () => {
  test('app loads with title bar, sidebar and composer visible', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Title bar
    await expect(page.locator('header')).toBeVisible()

    // Sidebar
    await expect(page.locator('aside.hk-sidebar')).toBeVisible()
    await expect(page.locator('aside.hk-sidebar')).toContainText('HakusAI')
    await expect(page.locator('aside.hk-sidebar input[placeholder="搜索会话..."]')).toBeVisible()

    // Composer placeholder (connection may be offline in test env)
    await expect(page.getByPlaceholder(/未连接到\s*服务|Send a message/)).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('sidebar new chat button creates a session', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForSelector('aside.hk-sidebar', { state: 'visible' })

    const newChatButton = page.locator('aside.hk-sidebar button[title="New chat"]')
    await expect(newChatButton).toBeVisible()
    await newChatButton.click()

    // A new session item should appear
    await expect(page.locator('aside.hk-sidebar').locator('text=New Chat').first()).toBeVisible()

    expect(errors).toHaveLength(0)
  })

  test('session actions menu provides rename and delete', async ({ page }) => {
    const errors = await collectConsoleErrors(page)
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await page.waitForSelector('aside.hk-sidebar', { state: 'visible' })

    // Create a session first
    await page.locator('aside.hk-sidebar button[title="New chat"]').click()
    await expect(page.locator('aside.hk-sidebar').locator('text=New Chat').first()).toBeVisible()
    // Wait for session list to stabilize (avoid detachment during re-render)
    await page.waitForLoadState('networkidle')

    // Open the action menu of the newly created session (not a WeChat session)
    const newSessionItem = page.locator('aside.hk-sidebar').locator('text=New Chat').first().locator('xpath=ancestor::*[contains(@class, "group")]')
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
    await page.waitForSelector('aside.hk-sidebar', { state: 'visible' })

    // Sidebar wrapper should start open and have the expected width
    const sidebarWrapper = page.locator('[data-testid="sidebar-wrapper"]')
    await expect(sidebarWrapper).toHaveCSS('width', /256px|16rem/)

    // Toggle off
    await page.locator('header button[title="切换侧栏"]').click()
    await expect(sidebarWrapper).toHaveCSS('width', /^0px$/)

    // Reload and verify sidebar is still closed
    await page.reload()
    await page.waitForLoadState('networkidle')
    await expect(sidebarWrapper).toHaveCSS('width', /^0px$/)

    // Toggle back on
    await page.locator('header button[title="切换侧栏"]').click()
    await expect(sidebarWrapper).toHaveCSS('width', /256px|16rem/)

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

    // Mock health & version endpoints so the composer is enabled (connState=connected)
    await page.route('**/health', async (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', version: '0.1.0', model_loaded: true, agent_ready: true }),
      })
    })
    await page.route('**/api/version', async (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sidecar_api_version: '0.8.0',
          sidecar_api_version_int: 8,
          server_version: '0.1.0',
          endpoints: [],
        }),
      })
    })
    await page.route('**/api/config', async (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          version: '0.1.0',
          character: { name: 'HakusAI', personality: '' },
          model: { provider: 'opencode', model_name: 'deepseek-v4-flash-free' },
          voice: { enabled: false, asr_provider: '', tts_provider: '' },
          avatar: { enabled: false, type: '', name: '' },
        }),
      })
    })

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
    await page.waitForSelector('aside.hk-sidebar', { state: 'visible' })

    // Create a new session
    await page.locator('aside button[title="New chat"]').click()
    await expect(page.locator('aside.hk-sidebar').locator('text=New Chat').first()).toBeVisible()

    // Send any message — the mocked stream will produce ask_user
    const composer = page.locator('textarea').first()
    await expect(composer).toBeVisible()
    await composer.fill('trigger ask_user')
    // Wait for Send button to become enabled (connection check may still be in-flight)
    await expect(page.locator('button[title="Send"]')).toBeEnabled({ timeout: 15000 })
    await page.locator('button[title="Send"]').click()

    // Wait for the interactive question card
    const questionCard = page.locator('text=羽汐想问').first().locator('xpath=ancestor::*[contains(@class, "rounded-")][1]')
    await expect(questionCard).toBeVisible({ timeout: 10000 })
    const optionButtons = questionCard.locator('div[class="space-y-1.5"] > button')
    await expect(optionButtons.first()).toBeVisible()

    // Select the first option, then confirm
    const firstOptionText = await optionButtons.first().locator('span.flex-1').textContent()
    await optionButtons.first().click()
    // Wait for state update (selected option) before clicking confirm
    await page.waitForTimeout(300)
    await questionCard.locator('button:has-text("继续")').click()

    // Verify answered state shows the selected option and answer was posted
    await expect(questionCard.locator('text=已选择')).toBeVisible({ timeout: 10000 })
    if (firstOptionText) {
      await expect(questionCard.locator(`text=${firstOptionText}`)).toBeVisible()
    }
    expect(answerReceived).toBe(true)

    expect(errors).toHaveLength(0)
  })
})
