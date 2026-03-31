const { chromium } = require('playwright');
const fs = require('fs');
const { execSync } = require('child_process');

const FRONT = 'http://127.0.0.1:5173';
const API = 'http://127.0.0.1:8080/api';
const env = JSON.parse(fs.readFileSync('/tmp/verify_summary_env.json', 'utf8'));

async function api(path, { method = 'GET', body } = {}) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${env.token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${method} ${path} ${response.status}: ${JSON.stringify(payload)}`);
  }
  return payload;
}

function clearSummaryCaches() {
  execSync(
    `cd /Users/taless/Code/notebooklm && docker compose exec -T postgres psql -U postgres -d notebooklm -c "delete from summary_caches where article_id='${env.articleId}';"`,
    { stdio: 'ignore' },
  );
  execSync(
    `cd /Users/taless/Code/notebooklm && docker compose exec -T redis sh -lc "redis-cli --scan --pattern 'notebooklm:summary:${env.articleId}:*' | xargs -r redis-cli del"`,
    { stdio: 'ignore' },
  );
}

function readTempUnavailableRedis() {
  const key = execSync(
    `cd /Users/taless/Code/notebooklm && docker compose exec -T redis sh -lc "redis-cli --scan --pattern 'notebooklm:summary:${env.articleId}:*' | head -n 1"`,
    { encoding: 'utf8' },
  ).trim();
  if (!key) return { key: '', ttl: -1, temporaryUnavailable: false, summaryText: '' };
  const ttlRaw = execSync(
    `cd /Users/taless/Code/notebooklm && docker compose exec -T redis redis-cli ttl '${key}'`,
    { encoding: 'utf8' },
  ).trim();
  const valueRaw = execSync(
    `cd /Users/taless/Code/notebooklm && docker compose exec -T redis redis-cli get '${key}'`,
    { encoding: 'utf8' },
  ).trim();
  let parsed = {};
  try { parsed = JSON.parse(valueRaw); } catch { parsed = {}; }
  return {
    key,
    ttl: Number(ttlRaw),
    temporaryUnavailable: Boolean(parsed.temporaryUnavailable),
    summaryText: String(parsed.summary_text || ''),
  };
}

(async () => {
  let modelTestFeedback = '';
  let summaryBodyText = '';
  try {
    const articlePayload = await api(`/notebooks/${env.notebookId}/articles/${env.articleId}`, {
      method: 'GET',
    });
    const articleTitle = String(articlePayload?.item?.title || '').trim();
    await api('/settings', {
      method: 'PUT',
      body: {
        useDefaultModelConfig: false,
        modelProvider: 'openai',
        modelName: 'gpt-4.1',
        apiUrl: 'http://127.0.0.1:9/v1',
        apiKey: 'sk-invalid-summary-test-key',
      },
    });
    clearSummaryCaches();

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
    if (articleTitle) {
      const targetArticleItem = page.locator('.nb-article-item', { hasText: articleTitle.slice(0, 24) }).first();
      if (await targetArticleItem.count()) {
        await targetArticleItem.click();
      }
    }

    await page.locator('button[title="设置"]').first().click();
    await page.waitForSelector('.settings-modal', { timeout: 10000 });
    await page.locator('.settings-tab', { hasText: '聊天模型' }).first().click();
    await page.locator('.settings-inline-actions .settings-save-btn', { hasText: '测试连接' }).first().click();
    await page.waitForFunction(() => {
      const el = document.querySelector('.settings-inline-feedback');
      return Boolean(el && (el.textContent || '').trim());
    }, null, { timeout: 45000 });
    modelTestFeedback = (await page.locator('.settings-inline-feedback').first().textContent())?.trim() || '';
    await page.locator('.settings-close').first().click();

    await page.waitForSelector('.nb-toolbar-right .nb-icon-btn[title*="摘要"]:not([disabled])', { timeout: 45000 });
    const summaryClicked = await page.evaluate(() => {
      const buttons = Array.from(document.querySelectorAll('.nb-toolbar-right .nb-icon-btn[title*="摘要"]'));
      const target = buttons.find((btn) => btn instanceof HTMLElement && btn.offsetParent !== null && !btn.hasAttribute('disabled'));
      if (target instanceof HTMLElement) {
        target.click();
        return true;
      }
      return false;
    });
    if (!summaryClicked) {
      throw new Error('未找到可点击的摘要按钮');
    }
    await page.waitForSelector('.nb-summary-card', { timeout: 20000 });
    let summaryUnavailableVisible = false;
    try {
      await page.waitForFunction(() => {
        const txt = (document.querySelector('.nb-summary-body')?.textContent || '').trim();
        return txt.length > 0 && txt.includes('摘要服务暂时不可用');
      }, null, { timeout: 210000 });
      summaryUnavailableVisible = true;
    } catch {
      summaryUnavailableVisible = false;
    }

    const summaryState = await page.evaluate(() => ({
      hasSummaryCard: Boolean(document.querySelector('.nb-summary-card')),
      hasSummaryBody: Boolean(document.querySelector('.nb-summary-body')),
      summaryBodyText: (document.querySelector('.nb-summary-body')?.textContent || '').trim(),
      loading: Boolean(document.querySelector('.nb-summary-loading')),
    }));
    summaryBodyText = summaryState.summaryBodyText || '';
    await page.screenshot({ path: '/tmp/verify-issue4-5-summary-model.png', fullPage: true });
    await browser.close();

    const redisState = readTempUnavailableRedis();
    console.log(JSON.stringify({
      notebookId: env.notebookId,
      articleId: env.articleId,
      modelTestFeedback,
      summaryContainsUnavailable: summaryBodyText.includes('摘要服务暂时不可用'),
      summaryUnavailableVisible,
      summaryPreview: summaryBodyText.slice(0, 120),
      summaryState,
      redisState,
      screenshot: '/tmp/verify-issue4-5-summary-model.png',
    }, null, 2));
  } finally {
    await api('/settings', {
      method: 'PUT',
      body: {
        useDefaultModelConfig: true,
        clearApiKey: true,
      },
    }).catch(() => {});
  }
})();
