const { chromium } = require('playwright');
const fs = require('fs');

const FRONT = 'http://127.0.0.1:5173';
const env = JSON.parse(fs.readFileSync('/tmp/verify_summary_env.json', 'utf8'));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1536, height: 1120 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, {
    token: env.token,
    user: { id: env.userId, name: env.username, email: env.email },
  });

  const page = await context.newPage();
  await page.goto(`${FRONT}/notebook/${env.notebookId}?articleId=${env.articleId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });

  await page.waitForFunction(() => document.querySelectorAll('.nb-toc-item').length > 0, null, { timeout: 15000 });
  const tocCount = await page.locator('.nb-toc-item').count();

  await page.locator('button[title="设置"]').first().click();
  await page.waitForSelector('.settings-modal', { timeout: 10000 });
  const chatModelTab = page.locator('.settings-tab', { hasText: '聊天模型' }).first();
  if (await chatModelTab.count()) {
    await chatModelTab.click();
  }
  await page.waitForSelector('.settings-inline-actions .settings-save-btn', { timeout: 10000 });
  await page.locator('.settings-inline-actions .settings-save-btn', { hasText: '测试连接' }).first().click();
  await page.waitForFunction(() => {
    const el = document.querySelector('.settings-inline-feedback');
    return Boolean(el && (el.textContent || '').trim().length > 0);
  }, null, { timeout: 45000 });
  const modelTestFeedback = (await page.locator('.settings-inline-feedback').first().textContent())?.trim() || '';
  await page.locator('.settings-close').first().click();

  await page.waitForFunction(() => {
    const body = document.querySelector('.nb-article-markdown');
    return Boolean(body && (body.textContent || '').includes('测试文档'));
  }, null, { timeout: 20000 });

  const summaryBtn = page.locator('.nb-icon-btn[title="AI 摘要"]').first();
  await summaryBtn.click();
  await page.waitForSelector('.nb-summary-card', { timeout: 15000 });
  await page.waitForFunction(() => {
    const body = document.querySelector('.nb-summary-body');
    return Boolean(body && (body.textContent || '').includes('摘要服务暂时不可用'));
  }, null, { timeout: 70000 });
  const summaryText = (await page.locator('.nb-summary-body').first().innerText()).trim();

  await page.screenshot({ path: '/tmp/verify-summary-toc-settings.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId: env.notebookId,
    articleId: env.articleId,
    tocCount,
    modelTestFeedback,
    summaryContainsUnavailable: summaryText.includes('摘要服务暂时不可用'),
    summaryPreview: summaryText.slice(0, 120),
  }, null, 2));
})();
