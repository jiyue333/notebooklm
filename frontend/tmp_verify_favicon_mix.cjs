const { chromium } = require('playwright');

const API = 'http://127.0.0.1:8080/api';
const FRONT = 'http://127.0.0.1:5173';

async function req(path, { method = 'GET', token, body } = {}) {
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
  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `icon-check-${stamp}` } }))?.item?.id;

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
  await page.waitForSelector('.sp-summary-card', { timeout: 160000 });
  await page.waitForSelector('.sp-summary-item', { timeout: 20000 });

  const summaryIconState = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('.sp-summary-favicon-wrap.has-image')).map((wrap) => {
      const img = wrap.querySelector('img');
      const fallback = wrap.querySelector('.sp-summary-favicon-fallback');
      const fallbackDisplay = fallback ? window.getComputedStyle(fallback).display : '';
      return {
        loaded: Boolean(img && img.complete && img.naturalWidth > 0),
        fallbackDisplay,
      };
    });
  });

  await page.locator('.sp-summary-view-btn').first().click();
  await page.waitForSelector('.sp-detail-shell', { timeout: 10000 });
  await page.waitForSelector('.sp-result-row', { timeout: 10000 });

  const detailIconState = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('.sp-result-favicon-wrap.has-image')).map((wrap) => {
      const img = wrap.querySelector('img');
      const fallback = wrap.querySelector('.sp-result-favicon-fallback');
      const fallbackDisplay = fallback ? window.getComputedStyle(fallback).display : '';
      return {
        loaded: Boolean(img && img.complete && img.naturalWidth > 0),
        fallbackDisplay,
      };
    });
  });

  const mixedSummary = summaryIconState.filter((item) => item.loaded && item.fallbackDisplay !== 'none').length;
  const mixedDetail = detailIconState.filter((item) => item.loaded && item.fallbackDisplay !== 'none').length;

  await page.screenshot({ path: '/tmp/verify-favicon-mix.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId,
    summaryIconCount: summaryIconState.length,
    detailIconCount: detailIconState.length,
    mixedSummary,
    mixedDetail,
    screenshot: '/tmp/verify-favicon-mix.png',
  }, null, 2));
})();
