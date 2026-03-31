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

(async () => {
  let modelTestFeedback = '';
  let summaryText = '';
  try {
    await api('/settings', {
      method: 'PUT',
      body: {
        useDefaultModelConfig: false,
        modelProvider: 'openai',
        modelName: 'gpt-4.1',
        apiUrl: 'https://api.openai.com/v1',
        apiKey: 'sk-invalid-for-summary-fallback-test',
      },
    });
    execSync(
      "cd /Users/taless/Code/notebooklm && docker compose exec -T postgres psql -U postgres -d notebooklm -c \"delete from summary_caches where article_id='4fb71903-8c90-425d-bf81-99b26a87917a';\"",
      { stdio: 'ignore' },
    );
    execSync(
      "cd /Users/taless/Code/notebooklm && docker compose exec -T redis redis-cli --scan --pattern 'notebooklm:summary:4fb71903-8c90-425d-bf81-99b26a87917a:*' | xargs -r docker compose exec -T redis redis-cli del",
      { stdio: 'ignore' },
    );

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
    await page.waitForSelector('.nb-article-item', { timeout: 20000 });
    await page.locator('.nb-article-item').first().click();
    await page.waitForSelector('.nb-toolbar-right .nb-icon-btn[title*="摘要"]', { timeout: 20000 });

    await page.locator('button[title="设置"]').first().click();
    await page.waitForSelector('.settings-modal', { timeout: 10000 });
    const chatModelTab = page.locator('.settings-tab', { hasText: '聊天模型' }).first();
    if (await chatModelTab.count()) {
      await chatModelTab.click();
    }
    await page.waitForSelector('.settings-inline-actions .settings-save-btn', { timeout: 10000 });
    await page.locator('.settings-inline-actions .settings-save-btn', { hasText: '测试连接' }).first().click();
    await page.waitForFunction(() => {
      const el = document.querySelector('.settings-inline-feedback');
      return Boolean(el && (el.textContent || '').trim().length > 0);
    }, null, { timeout: 45000 });
    modelTestFeedback = (await page.locator('.settings-inline-feedback').first().textContent())?.trim() || '';
    await page.locator('.settings-close').first().click();

    await page.waitForSelector('.nb-article-markdown', { timeout: 20000 });
    const summaryByTitle = page.locator('.nb-toolbar-right .nb-icon-btn[title*="摘要"]').first();
    if (await summaryByTitle.count()) {
      await page.evaluate(() => {
        const candidates = Array.from(document.querySelectorAll('.nb-toolbar-right .nb-icon-btn[title*="摘要"]'));
        const btn = candidates.find((item) => item instanceof HTMLElement && item.offsetParent !== null) || candidates[0];
        if (btn instanceof HTMLElement) btn.click();
      });
    } else {
      await page.evaluate(() => {
        const buttons = document.querySelectorAll('.nb-toolbar-right .nb-icon-btn');
        const btn = buttons.item(1);
        if (btn instanceof HTMLElement) btn.click();
      });
    }
    await page.waitForSelector('.nb-summary-card', { timeout: 15000 });
    try {
      await page.waitForFunction(() => {
        const body = document.querySelector('.nb-summary-body');
        return Boolean(body && (body.textContent || '').includes('摘要服务暂时不可用'));
      }, null, { timeout: 70000 });
    } catch {
      await page.waitForTimeout(1500);
    }

    const summaryDebug = await page.evaluate(() => {
      const summaryBtn = document.querySelector('.nb-toolbar-right .nb-icon-btn[title*="摘要"]');
      return {
        cardCount: document.querySelectorAll('.nb-summary-card').length,
        loading: Boolean(document.querySelector('.nb-summary-loading')),
        summaryBodyText: (document.querySelector('.nb-summary-body')?.textContent || '').trim(),
        summaryButtonDisabled: Boolean(summaryBtn && summaryBtn.hasAttribute('disabled')),
        summaryButtonTitle: summaryBtn?.getAttribute('title') || '',
      };
    });
    summaryText = summaryDebug.summaryBodyText;
    await page.screenshot({ path: '/tmp/verify-model-test-summary-unavailable.png', fullPage: true });
    await browser.close();

    console.log(JSON.stringify({
      notebookId: env.notebookId,
      articleId: env.articleId,
      modelTestFeedback,
      summaryDebug,
      summaryContainsUnavailable: summaryText.includes('摘要服务暂时不可用'),
      summaryPreview: summaryText.slice(0, 140),
      screenshot: '/tmp/verify-model-test-summary-unavailable.png',
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
