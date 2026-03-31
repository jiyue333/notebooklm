const { chromium } = require('playwright');
const fs = require('fs');

const FRONT = 'http://127.0.0.1:5173';
const env = JSON.parse(fs.readFileSync('/tmp/verify_summary_env.json', 'utf8'));

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1080 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, {
    token: env.token,
    user: { id: env.userId, name: env.username, email: env.email },
  });

  const page = await context.newPage();
  await page.goto(`${FRONT}/notebook/${env.notebookId}?articleId=${env.articleId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });
  await page.waitForSelector('.nb-article-item', { timeout: 20000 });

  const iconChecks = await page.$$eval('.nb-article-item', (rows) => rows.map((row) => {
    const svgIcon = row.querySelector('.nb-article-icon svg');
    if (svgIcon) {
      return { hasIcon: true, type: 'svg', title: (row.querySelector('.nb-article-title-text')?.textContent || '').trim() };
    }
    const wrap = row.querySelector('.nb-article-icon-wrap');
    if (!wrap) {
      return { hasIcon: false, type: 'none', title: (row.querySelector('.nb-article-title-text')?.textContent || '').trim() };
    }
    const img = wrap.querySelector('img');
    const fallback = wrap.querySelector('.nb-article-icon-fallback');
    const imgVisible = !!img && getComputedStyle(img).display !== 'none';
    const fbVisible = !!fallback && getComputedStyle(fallback).display !== 'none';
    return {
      hasIcon: imgVisible || fbVisible,
      type: imgVisible ? 'favicon' : (fbVisible ? 'fallback' : 'none'),
      title: (row.querySelector('.nb-article-title-text')?.textContent || '').trim(),
    };
  }));

  const rows = page.locator('.nb-article-item');
  const count = Math.min(await rows.count(), 8);
  const tocAudit = [];
  for (let i = 0; i < count; i += 1) {
    await rows.nth(i).click();
    await page.waitForTimeout(700);
    const audit = await page.evaluate(() => {
      const title = (document.querySelector('.nb-article-title')?.textContent || '').trim();
      const body = document.querySelector('.nb-article-markdown');
      const headings = body ? body.querySelectorAll('h1, h2, h3, h4').length : 0;
      const tocCount = document.querySelectorAll('.nb-toc-item').length;
      const contentBlocked = !!document.querySelector('.nb-article-pending');
      return { title, headings, tocCount, contentBlocked };
    });
    tocAudit.push(audit);
  }

  await page.screenshot({ path: '/tmp/verify-toc-icons.png', fullPage: true });
  await browser.close();

  const tocMissingCases = tocAudit.filter((item) => item.headings > 1 && item.tocCount === 0);
  const iconMissingCases = iconChecks.filter((item) => !item.hasIcon);

  console.log(JSON.stringify({
    articleCount: iconChecks.length,
    iconMissingCount: iconMissingCases.length,
    iconMissingCases,
    tocAudit,
    tocMissingCount: tocMissingCases.length,
    tocMissingCases,
    screenshot: '/tmp/verify-toc-icons.png',
  }, null, 2));
})();
