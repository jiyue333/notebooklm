const { chromium } = require('playwright');
const fs = require('fs');

const FRONT = 'http://127.0.0.1:5173';
const env = JSON.parse(fs.readFileSync('/tmp/verify_summary_env.json', 'utf8'));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, {
    token: env.token,
    user: { id: env.userId, name: env.username, email: env.email },
  });

  const page = await context.newPage();
  await page.goto(`${FRONT}/notebook/${env.notebookId}?articleId=${env.articleId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });
  await page.waitForSelector('.nb-article-markdown', { timeout: 20000 });

  await page.waitForFunction(() => {
    const headingCount = document.querySelectorAll('.nb-article-markdown h1, .nb-article-markdown h2, .nb-article-markdown h3').length;
    const tocCount = document.querySelectorAll('.nb-toc-item').length;
    return headingCount > 1 && tocCount > 0;
  }, null, { timeout: 15000 });

  const stats = await page.evaluate(() => {
    const headingCount = document.querySelectorAll('.nb-article-markdown h1, .nb-article-markdown h2, .nb-article-markdown h3').length;
    const tocCount = document.querySelectorAll('.nb-toc-item').length;
    const tocTexts = Array.from(document.querySelectorAll('.nb-toc-item a')).slice(0, 6).map((el) => (el.textContent || '').trim());
    return { headingCount, tocCount, tocTexts };
  });

  await page.screenshot({ path: '/tmp/verify-toc-fallback.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId: env.notebookId,
    articleId: env.articleId,
    ...stats,
    screenshot: '/tmp/verify-toc-fallback.png',
  }, null, 2));
})();
