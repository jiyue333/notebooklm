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

async function waitForArticleReady({ token, notebookId, articleId, timeoutMs = 180000 }) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const detail = await req(`/notebooks/${notebookId}?contentArticleId=${articleId}`, { token });
    const article = (detail?.item?.articles || []).find((row) => row.id === articleId);
    if (article && article.parseStatus === 'ready' && article.contentReady) {
      return detail.item;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
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
  const notebookId = (await req('/notebooks', { method: 'POST', token, body: { title: `img-proxy-${stamp}` } }))?.item?.id;

  const markdown = [
    '# 图片测试',
    '',
    '这是一张外链图片：',
    '',
    '![react-logo](https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/React-icon.svg/256px-React-icon.svg.png)',
    '',
    '结束。',
  ].join('\n');

  const created = await req(`/notebooks/${notebookId}/sources`, {
    method: 'POST',
    token,
    body: {
      sourceType: 'text',
      title: '图片渲染测试',
      content: markdown,
    },
  });
  const articleId = created?.item?.articles?.[0]?.id;
  if (!articleId) {
    throw new Error('article id missing');
  }

  await waitForArticleReady({ token, notebookId, articleId });

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1536, height: 1100 } });
  await context.addInitScript((session) => {
    localStorage.setItem('notebooklm-session', JSON.stringify(session));
  }, { token, user });
  const page = await context.newPage();
  await page.goto(`${FRONT}/notebook/${notebookId}?articleId=${articleId}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.nb-layout', { timeout: 30000 });
  await page.waitForSelector('.nb-article-content img', { timeout: 90000 });

  const imageState = await page.evaluate(() => {
    const images = Array.from(document.querySelectorAll('.nb-article-content img'));
    return images.map((img) => ({
      src: img.getAttribute('src') || '',
      fallbackTried: img.dataset.fallbackTried || '',
      naturalWidth: img.naturalWidth || 0,
      isBroken: img.classList.contains('nb-broken-image'),
    }));
  });

  await page.screenshot({ path: '/tmp/verify-markdown-image-proxy.png', fullPage: true });
  await browser.close();

  console.log(JSON.stringify({
    notebookId,
    articleId,
    imageState,
    proxiedCount: imageState.filter((item) => item.src.includes('/api/notebooks/media/image-proxy?url=')).length,
    screenshot: '/tmp/verify-markdown-image-proxy.png',
  }, null, 2));
})();

