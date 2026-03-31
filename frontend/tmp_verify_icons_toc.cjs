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

async function waitForArticleReady(notebookId, articleId, token, timeoutMs = 120000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const detail = await req(`/notebooks/${notebookId}/articles/${articleId}`, { token });
    const item = detail?.item || detail;
    if (item?.contentReady) {
      return item;
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  throw new Error('article not ready in time');
}

(async () => {
  const stamp = Date.now();
  const username = `u${stamp}`;
  const email = `${username}@example.com`;
  const password = 'Passw0rd!';

  const reg = await req('/auth/register', { method: 'POST', body: { username, email, password } });
  const token = reg?.item?.token || reg?.token;
  const user = reg?.item?.user || { id: `u-${stamp}`, name: username, email };

  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `verify-${stamp}` } }))?.item?.id;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, { token, user });
  const page = await context.newPage();

  // --- verify source icons after web search import ---
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
    return Boolean(card && card.querySelectorAll('.sp-summary-item').length > 0);
  }, null, { timeout: 150000 });

  await page.locator('.sp-summary-view-btn').first().click();
  await page.waitForSelector('.sp-detail-shell', { timeout: 10000 });
  await page.locator('.sp-import-btn').last().click();

  await page.waitForSelector('.nb-article-item', { timeout: 30000 });
  await page.waitForTimeout(1200);
  const articleCount = await page.locator('.nb-article-item').count();
  const faviconCount = await page.locator('.nb-article-favicon').count();

  // --- verify TOC visibility from article toc_json ---
  const markdown = [
    '# 测试文档',
    '',
    '## 第一节',
    '段落 A',
    '',
    '## 第二节',
    '段落 B',
    '',
    '### 第二节-小节',
    '段落 C',
  ].join('\n');

  const createRes = await req(`/notebooks/${notebookId}/sources`, {
    method: 'POST',
    token,
    body: { sourceType: 'text', title: 'toc-test', content: markdown },
  });

  const detail = createRes?.item;
  const addedArticle = (detail?.articles || []).find((a) => a.title === 'toc-test');
  if (!addedArticle?.id) throw new Error('toc-test article missing');

  const readyArticle = await waitForArticleReady(notebookId, addedArticle.id, token);
  await page.goto(`${FRONT}/notebook/${notebookId}?articleId=${addedArticle.id}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });

  await page.waitForFunction(() => {
    const list = document.querySelectorAll('.nb-toc-item');
    return list.length > 0;
  }, null, { timeout: 20000 });

  const tocUiCount = await page.locator('.nb-toc-item').count();
  const tocBackendCount = Array.isArray(readyArticle.toc) ? readyArticle.toc.length : 0;
  await page.screenshot({ path: '/tmp/verify-icons-toc.png', fullPage: true });

  await browser.close();

  console.log(JSON.stringify({
    notebookId,
    sourceIcons: { articleCount, faviconCount },
    toc: { tocUiCount, tocBackendCount },
  }, null, 2));
})();
