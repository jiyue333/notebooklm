const { chromium } = require('playwright');

const API = 'http://127.0.0.1:8080/api';
const FRONT = 'http://127.0.0.1:5173';

async function req(path, { method='GET', token, body } = {}) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`${method} ${path} ${res.status}: ${JSON.stringify(json)}`);
  return json;
}

(async () => {
  const stamp = Date.now();
  const username = `u${stamp}`;
  const email = `${username}@example.com`;
  const password = 'Passw0rd!';

  const reg = await req('/auth/register', { method: 'POST', body: { username, email, password } });
  const token = reg?.token || reg?.item?.token;
  const user = reg?.user || reg?.item?.user || { id: `u-${stamp}`, name: username, email };
  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `icon-${stamp}` } }))?.item?.id;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1536, height: 1120 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, { token, user });
  const page = await context.newPage();

  await page.goto(`${FRONT}/notebook/${notebookId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });

  if (await page.locator('.add-source-overlay').count()) {
    const closeBtn = page.locator('.add-source-close').first();
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click();
      await page.waitForTimeout(300);
    }
  }

  await page.locator('.sp-search-input').first().fill('找一些关于单元测试的技巧博客');
  await page.locator('.sp-submit-btn').first().click();
  await page.waitForFunction(() => {
    const card = document.querySelector('.sp-summary-card');
    return Boolean(card && card.querySelectorAll('.sp-summary-item').length > 0);
  }, null, { timeout: 150000 });

  await page.locator('.sp-summary-view-btn').first().click();
  await page.waitForSelector('.sp-detail-shell', { timeout: 10000 });
  await page.locator('.sp-import-btn').last().click();

  await page.waitForSelector('.nb-article-item', { timeout: 40000 });
  await page.waitForTimeout(2000);

  const articleCount = await page.locator('.nb-article-item').count();
  const faviconCount = await page.locator('.nb-article-favicon').count();
  const fallbackIconCount = await page.locator('.nb-article-icon').count();

  await page.screenshot({ path: '/tmp/verify-source-icons.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({ notebookId, articleCount, faviconCount, fallbackIconCount }, null, 2));
})();
