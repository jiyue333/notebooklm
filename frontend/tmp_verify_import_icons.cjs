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
  if (!res.ok) {
    throw new Error(`${method} ${path} ${res.status}: ${JSON.stringify(json)}`);
  }
  return json;
}

(async () => {
  const stamp = Date.now();
  const username = `uicons${stamp}`;
  const email = `${username}@example.com`;
  const password = 'Passw0rd!';

  const reg = await req('/auth/register', { method: 'POST', body: { username, email, password } });
  const token = reg?.item?.token || reg?.token;
  const user = reg?.item?.user || { id: `u-${stamp}`, name: username, email };
  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `icons-${stamp}` } }))?.item?.id;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1480, height: 1080 } });
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
    const card = document.querySelector('.sp-summary-card');
    if (!card) return false;
    return card.querySelectorAll('.sp-summary-item').length > 0;
  }, null, { timeout: 150000 });

  await page.locator('.sp-import-btn').first().click();
  await page.waitForFunction(() => document.querySelectorAll('.nb-article-item').length >= 3, null, { timeout: 40000 });

  const iconCheck = await page.$$eval('.nb-article-item', (rows) => rows.map((row) => {
    const title = (row.querySelector('.nb-article-title-text')?.textContent || '').trim();
    const svgIcon = row.querySelector('.nb-article-icon svg');
    if (svgIcon) return { title, hasIcon: true, type: 'svg' };
    const wrap = row.querySelector('.nb-article-icon-wrap');
    if (!wrap) return { title, hasIcon: false, type: 'none' };
    const img = wrap.querySelector('.nb-article-favicon');
    const fallback = wrap.querySelector('.nb-article-icon-fallback');
    const imgVisible = !!img && getComputedStyle(img).display !== 'none';
    const fbVisible = !!fallback && getComputedStyle(fallback).display !== 'none';
    return { title, hasIcon: imgVisible || fbVisible, type: imgVisible ? 'favicon' : (fbVisible ? 'fallback' : 'none') };
  }));

  await page.screenshot({ path: '/tmp/verify-import-icons.png', fullPage: true });
  await browser.close();

  const missing = iconCheck.filter((item) => !item.hasIcon);
  console.log(JSON.stringify({
    notebookId,
    articleCount: iconCheck.length,
    missingIconCount: missing.length,
    missing,
    sample: iconCheck.slice(0, 8),
    screenshot: '/tmp/verify-import-icons.png',
  }, null, 2));
})();
