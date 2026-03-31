const { chromium } = require('playwright');
const fs = require('fs');

const front = 'http://127.0.0.1:5173';
const env = fs.readFileSync('/tmp/open_multi_env.txt', 'utf8').trim().split('\n').reduce((acc, line) => {
  const [k, ...rest] = line.split('=');
  acc[k] = rest.join('=');
  return acc;
}, {});

(async () => {
  const token = env.TOKEN;
  const notebookId = env.NBID;
  if (!token || !notebookId) throw new Error('missing token/notebook id');

  const session = {
    token,
    user: { id: 'perf-user', name: 'perf-user', email: 'perf-user@example.com', avatar: null },
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1728, height: 1117 } });
  await context.addInitScript((storedSession) => {
    window.localStorage.setItem('notebooklm-session', JSON.stringify(storedSession));
  }, session);
  const page = await context.newPage();

  const t0 = Date.now();
  await page.goto(`${front}/notebook/${notebookId}`, { waitUntil: 'domcontentloaded' });
  const tDom = Date.now();

  await page.waitForSelector('.nb-topbar', { timeout: 30000 });
  const tTopbar = Date.now();

  await page.waitForSelector('.nb-markdown-content, .nb-empty-center', { timeout: 30000 });
  const tContent = Date.now();

  const nav = await page.evaluate(() => {
    const e = performance.getEntriesByType('navigation')[0];
    return e ? {
      domContentLoaded: e.domContentLoadedEventEnd,
      loadEventEnd: e.loadEventEnd,
      responseEnd: e.responseEnd,
      transferSize: e.transferSize,
      encodedBodySize: e.encodedBodySize,
      decodedBodySize: e.decodedBodySize,
      duration: e.duration,
    } : null;
  });

  await page.screenshot({ path: '/tmp/notebook-open-browser.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId,
    wall: {
      gotoDomMs: tDom - t0,
      topbarReadyMs: tTopbar - t0,
      contentReadyMs: tContent - t0,
    },
    navigation: nav,
  }, null, 2));
})();
