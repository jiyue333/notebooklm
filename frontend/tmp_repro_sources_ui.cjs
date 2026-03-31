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
  const token = reg?.item?.token || reg?.token;
  const user = reg?.item?.user || { id: `u-${stamp}`, name: username, email };

  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `nb-${stamp}` } }))?.item?.id;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
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
      await page.waitForTimeout(400);
    }
  }

  await page.locator('.sp-search-input').first().fill('找一些关于单元测试的技巧博客');
  await page.locator('.sp-submit-btn').first().click();

  await page.waitForFunction(() => {
    const err = document.querySelector('.sp-feedback-error');
    if (err) return true;
    const card = document.querySelector('.sp-summary-card');
    if (!card) return false;
    const rows = card.querySelectorAll('.sp-summary-item').length;
    return rows > 0;
  }, null, { timeout: 150000 });

  const previewCount = await page.locator('.sp-summary-item').count();
  const previewTitles = await page.locator('.sp-summary-item-title').allTextContents();
  const previewMoreText = await page.locator('.sp-summary-more-line').first().textContent().catch(() => '');
  const hasReasonInSummary = (await page.content()).includes('推荐理由');

  await page.screenshot({ path: '/tmp/repro-sources-summary.png', fullPage: true });

  if (await page.locator('.sp-summary-view-btn').count()) {
    await page.locator('.sp-summary-view-btn').first().click();
    await page.waitForSelector('.sp-detail-shell', { timeout: 10000 });
  }

  const detailCount = await page.locator('.sp-result-row').count();
  const detailFieldLabels = await page.locator('.sp-result-field-label').allTextContents();

  await page.screenshot({ path: '/tmp/repro-sources-detail.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId,
    previewCount,
    previewTitles,
    previewMoreText,
    detailCount,
    detailFieldLabels,
    hasReasonInSummary,
  }, null, 2));
})();
