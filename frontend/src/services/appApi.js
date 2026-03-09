import { mockNotebooks, mockSearchResults, mockUser } from '../data/mockData';
import { runtimeConfig } from '../config/runtime';

const SESSION_STORAGE_KEY = 'notebooklm-session';

const DEFAULT_SETTINGS = {
    outputLanguage: mockUser.settings?.outputLanguage || '中文',
    themeColor: 'ocean',
    colorMode: mockUser.settings?.theme || 'light',
    modelProvider: 'openai_compatible',
    modelName: mockUser.settings?.model || 'gpt-4o',
    apiUrl: 'http://host.docker.internal:8317/v1/chat/completions',
    searchProvider: 'exa',
    embeddingProvider: 'openai_compatible',
    embeddingModel: 'text-embedding-3-large',
    embeddingApiUrl: 'https://api.openai.com/v1',
    username: mockUser.name,
    apiKey: '',
    searchApiKey: '',
    embeddingApiKey: '',
};

const DEFAULT_NOTES_BY_NOTEBOOK_ID = {
    'nb-001': [
        {
            id: 'note-001',
            title: 'YOLO 目标检测技术核心要点总结',
            content: '## 核心要点\n\n- YOLO 系列在密集场景下的优势\n- YOLOv5 → YOLOv11 的演进路线\n- 与传统方法的性能对比',
            type: 'Briefing Doc',
            sources: 8,
            time: '65 天前',
        },
        {
            id: 'note-002',
            title: '论文阅读笔记',
            content: '### Count2Density\n\n需要关注 Count2Density 的方法论\n\n> 利用计数信息来生成密度图',
            type: '笔记',
            sources: 3,
            time: '昨天',
        },
    ],
};

const clone = (value) => {
    if (typeof structuredClone === 'function') {
        return structuredClone(value);
    }
    return JSON.parse(JSON.stringify(value));
};

const wait = (ms = 250) => new Promise((resolve) => setTimeout(resolve, ms));

const generateId = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const safeLocalStorage = () => (
    typeof window !== 'undefined' && window.localStorage ? window.localStorage : null
);

const getStoredSession = () => {
    const storage = safeLocalStorage();
    if (!storage) return null;

    const raw = storage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;

    try {
        return JSON.parse(raw);
    } catch {
        storage.removeItem(SESSION_STORAGE_KEY);
        return null;
    }
};

const setStoredSession = (session) => {
    const storage = safeLocalStorage();
    if (!storage) return;
    storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
};

const clearStoredSession = () => {
    const storage = safeLocalStorage();
    if (!storage) return;
    storage.removeItem(SESSION_STORAGE_KEY);
};

const formatTimestamp = (date = new Date()) => date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
}).replaceAll('/', '-');

const formatNotebookDate = (date = new Date()) => {
    const parts = new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
    }).formatToParts(date);
    const year = parts.find((part) => part.type === 'year')?.value || date.getFullYear();
    const month = parts.find((part) => part.type === 'month')?.value || date.getMonth() + 1;
    const day = parts.find((part) => part.type === 'day')?.value || date.getDate();
    return `${year}年${month}月${day}日`;
};

const maskApiKey = (apiKey) => (
    apiKey && apiKey.length >= 4 ? `••••${apiKey.slice(-4)}` : ''
);

const extractPlainExcerpt = (markdown) => markdown
    .replace(/^#.*$/gm, '')
    .replace(/[`*_>#-]/g, '')
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean) || '暂无摘要内容';

const createImportedArticle = (source, index) => ({
    id: generateId(`art-import-${index}`),
    title: source.title,
    type: 'article',
    icon: '🌐',
    author: 'Web Search',
    date: formatTimestamp(),
    selected: false,
    content: `# ${source.title}\n\n${source.description}\n\n来源链接：${source.url}`,
    toc: [],
});

const createUploadedArticle = (file, index) => ({
    id: generateId(`art-upload-${index}`),
    title: file.name,
    type: 'article',
    icon: '📎',
    author: 'Uploaded File',
    date: formatTimestamp(),
    selected: false,
    content: `# ${file.name}\n\n文件已上传，等待后端解析内容。\n\n- 文件大小：${file.size} bytes\n- 文件类型：${file.type || '未知类型'}`,
    toc: [],
});

const createManualSourceArticle = ({ sourceType, url, title, content }) => ({
    id: generateId('art-manual'),
    title: title || (sourceType === 'web' ? url : '粘贴文字来源'),
    type: 'article',
    icon: sourceType === 'web' ? '🌐' : '📝',
    author: sourceType === 'web' ? 'Manual Web Source' : 'Pasted Text',
    date: formatTimestamp(),
    selected: false,
    content: sourceType === 'web'
        ? `# ${title || url}\n\n来源链接：${url}\n\n该来源由用户手动添加，等待后端抓取正文。`
        : `# ${title || '粘贴文字来源'}\n\n${content || ''}`,
    toc: [],
});

const createNotebookRecord = ({ title, emoji = '📒', color = '#8B7355' }) => ({
    id: generateId('nb'),
    title: title?.trim() || 'Untitled notebook',
    emoji,
    color,
    date: formatNotebookDate(),
    sourceCount: 0,
    articles: [],
});

const getSearchModeLabel = (mode = 'auto') => {
    if (mode === 'fast') return 'Fast Research';
    if (mode === 'deep') return 'Deep Research';
    return 'Auto Research';
};

const buildSettingsView = (user, settings) => ({
    outputLanguage: settings.outputLanguage,
    themeColor: settings.themeColor,
    colorMode: settings.colorMode,
    modelProvider: settings.modelProvider,
    modelName: settings.modelName,
    apiUrl: settings.apiUrl,
    searchProvider: settings.searchProvider || 'exa',
    embeddingProvider: settings.embeddingProvider || 'openai_compatible',
    embeddingModel: settings.embeddingModel || 'text-embedding-3-large',
    embeddingApiUrl: settings.embeddingApiUrl || 'https://api.openai.com/v1',
    hasApiKey: Boolean(settings.apiKey),
    hasCustomApiKey: Boolean(settings.apiKey),
    usingDefaultApiKey: false,
    apiKeyMasked: maskApiKey(settings.apiKey),
    hasSearchApiKey: Boolean(settings.searchApiKey),
    hasCustomSearchApiKey: Boolean(settings.searchApiKey),
    usingDefaultSearchApiKey: false,
    searchApiKeyMasked: maskApiKey(settings.searchApiKey),
    hasEmbeddingApiKey: Boolean(settings.embeddingApiKey),
    hasCustomEmbeddingApiKey: Boolean(settings.embeddingApiKey),
    usingDefaultEmbeddingApiKey: false,
    embeddingApiKeyMasked: maskApiKey(settings.embeddingApiKey),
    username: user.name,
});

const buildMockTranslation = (article, targetLanguage) => {
    const excerpt = extractPlainExcerpt(article.content).slice(0, 240);
    return {
        translatedContent: `# ${article.title}\n\n> 以下为面向 ${targetLanguage} 的 mock 译文，真实后端接入后这里会替换为模型生成结果。\n\n## 译文摘要\n\n${excerpt}\n\n## 说明\n\n- 当前使用的是示例翻译结果\n- 正式版本会基于文章正文和目标语言生成完整译文`,
        targetLanguage,
    };
};

const createMockState = () => ({
    user: clone(mockUser),
    settings: clone(DEFAULT_SETTINGS),
    notebooks: clone(mockNotebooks),
    notesByNotebookId: clone(DEFAULT_NOTES_BY_NOTEBOOK_ID),
    searchSessionsById: {},
});

let mockState = createMockState();

const getNotebookRecord = (notebookId) => {
    const notebook = mockState.notebooks.find((item) => item.id === notebookId);
    if (!notebook) {
        throw new Error('未找到对应的笔记本');
    }
    return notebook;
};

const summarizeNotebook = (notebook) => ({
    id: notebook.id,
    title: notebook.title,
    emoji: notebook.emoji,
    color: notebook.color,
    date: notebook.date,
    sourceCount: notebook.articles?.length ?? notebook.sourceCount ?? 0,
});

const buildNotebookDetail = (notebookId) => {
    const notebook = clone(getNotebookRecord(notebookId));
    return {
        ...notebook,
        sourceCount: notebook.articles?.length ?? 0,
        notes: clone(mockState.notesByNotebookId[notebookId] || []),
    };
};

const ensureNotesBucket = (notebookId) => {
    if (!mockState.notesByNotebookId[notebookId]) {
        mockState.notesByNotebookId[notebookId] = [];
    }
    return mockState.notesByNotebookId[notebookId];
};

const buildMockSummary = (article) => ({
    summary: `${article.title} 主要围绕 ${extractPlainExcerpt(article.content).slice(0, 96)}。当前摘要为 mock 返回，后端接入后可直接替换为真实 LLM 结果。`,
});

const mockProvider = {
    async login({ username, password }) {
        await wait(350);
        if (!username?.trim() || !password?.trim()) {
            throw new Error('请输入用户名和密码');
        }

        mockState.user = {
            ...mockState.user,
            name: username.trim(),
            email: `${username.trim()}@example.com`,
        };
        mockState.settings.username = username.trim();

        const session = {
            token: 'mock-token',
            user: clone(mockState.user),
        };
        setStoredSession(session);
        return session;
    },

    async logout() {
        await wait(120);
        clearStoredSession();
        mockState = createMockState();
        return { success: true };
    },

    async getCurrentUser() {
        await wait(120);
        const session = getStoredSession();
        if (session?.user) {
            return clone(session.user);
        }
        return clone(mockState.user);
    },

    async listNotebooks({ query = '' } = {}) {
        await wait(180);
        const items = mockState.notebooks.map(summarizeNotebook);
        if (!query.trim()) return items;

        const normalized = query.trim().toLowerCase();
        return items.filter((item) => item.title.toLowerCase().includes(normalized));
    },

    async createNotebook(payload = {}) {
        await wait(220);
        const notebook = createNotebookRecord(payload);
        mockState.notebooks.unshift(notebook);
        mockState.notesByNotebookId[notebook.id] = [];
        return buildNotebookDetail(notebook.id);
    },

    async updateNotebook(notebookId, payload = {}) {
        await wait(180);
        const notebook = getNotebookRecord(notebookId);
        Object.assign(notebook, payload);
        return buildNotebookDetail(notebookId);
    },

    async deleteNotebook(notebookId) {
        await wait(180);
        mockState.notebooks = mockState.notebooks.filter((item) => item.id !== notebookId);
        delete mockState.notesByNotebookId[notebookId];
        return { success: true };
    },

    async getNotebookDetail(notebookId) {
        await wait(180);
        return buildNotebookDetail(notebookId);
    },

    async saveNote(notebookId, note) {
        await wait(220);
        const notes = ensureNotesBucket(notebookId);
        const nextNote = {
            id: note.id || `note-${Date.now()}`,
            title: note.title?.trim() || '无标题笔记',
            content: note.content || '',
            type: note.type || '笔记',
            sources: note.sources ?? 0,
            time: '刚刚',
        };

        const existingIndex = notes.findIndex((item) => item.id === nextNote.id);
        if (existingIndex >= 0) {
            notes[existingIndex] = nextNote;
        } else {
            notes.unshift(nextNote);
        }

        return clone(nextNote);
    },

    async deleteNote(notebookId, noteId) {
        await wait(150);
        const notes = ensureNotesBucket(notebookId);
        mockState.notesByNotebookId[notebookId] = notes.filter((item) => item.id !== noteId);
        return { success: true };
    },

    async searchSources({ notebookId, query, mode = 'auto', maxResults = 10 }) {
        await wait(mode === 'deep' ? 320 : 900);
        if (!query?.trim()) {
            return {
                searchSessionId: null,
                mode,
                modeLabel: getSearchModeLabel(mode),
                status: 'completed',
                execution: 'sync',
                items: [],
                meta: { provider: 'mock', elapsedMs: 0 },
            };
        }

        const normalized = query.trim().toLowerCase();
        const matched = clone(mockSearchResults).filter((item) => (
            item.title.toLowerCase().includes(normalized)
            || item.description.toLowerCase().includes(normalized)
        ));
        const items = (matched.length > 0 ? matched : clone(mockSearchResults))
            .slice(0, maxResults)
            .map((item, index) => ({
                ...item,
                id: generateId(`srr-${index}`),
            }));
        const searchSessionId = generateId('ss');
        const execution = mode === 'deep' ? 'async' : 'sync';
        mockState.searchSessionsById[searchSessionId] = {
            id: searchSessionId,
            notebookId,
            mode,
            modeLabel: getSearchModeLabel(mode),
            status: execution === 'async' ? 'queued' : 'completed',
            execution,
            items,
            readyAt: execution === 'async' ? Date.now() + 1500 : Date.now(),
        };

        if (execution === 'async') {
            await wait(1200);
            mockState.searchSessionsById[searchSessionId].status = 'completed';
            return {
                searchSessionId,
                mode,
                modeLabel: getSearchModeLabel(mode),
                status: 'completed',
                execution,
                items,
                message: 'search accepted',
            };
        }

        return {
            searchSessionId,
            mode,
            modeLabel: getSearchModeLabel(mode),
            status: 'completed',
            execution,
            items,
            meta: { provider: 'mock', elapsedMs: 900 },
        };
    },

    async getSearchSession({ searchSessionId }) {
        await wait(350);
        const session = mockState.searchSessionsById[searchSessionId];
        if (!session) {
            throw new Error('未找到对应搜索会话');
        }

        if (session.execution === 'async' && Date.now() >= session.readyAt) {
            session.status = 'completed';
        }

        return {
            searchSessionId: session.id,
            mode: session.mode,
            modeLabel: session.modeLabel,
            status: session.status,
            execution: session.execution,
            items: session.status === 'completed' ? clone(session.items) : [],
            meta: { provider: 'mock' },
        };
    },

    async importSources({ notebookId, searchSessionId, searchResultIds }) {
        await wait(260);
        const notebook = getNotebookRecord(notebookId);
        const session = mockState.searchSessionsById[searchSessionId];
        if (!session || session.notebookId !== notebookId) {
            throw new Error('搜索会话不存在或已失效');
        }
        const imported = (session.items || [])
            .filter((item) => searchResultIds.includes(item.id))
            .map((item, index) => createImportedArticle(item, index));

        if (imported.length > 0) {
            notebook.articles = [...imported, ...(notebook.articles || [])];
            notebook.sourceCount = notebook.articles.length;
        }

        return buildNotebookDetail(notebookId);
    },

    async createSource({ notebookId, sourceType, url, title, content }) {
        await wait(220);
        const notebook = getNotebookRecord(notebookId);
        notebook.articles = [
            createManualSourceArticle({ sourceType, url, title, content }),
            ...(notebook.articles || []),
        ];
        notebook.sourceCount = notebook.articles.length;
        return buildNotebookDetail(notebookId);
    },

    async uploadFiles({ notebookId, files }) {
        await wait(350);
        const notebook = getNotebookRecord(notebookId);
        const uploaded = Array.from(files || []).map((file, index) => createUploadedArticle(file, index));
        if (uploaded.length > 0) {
            notebook.articles = [...uploaded, ...(notebook.articles || [])];
            notebook.sourceCount = notebook.articles.length;
        }

        return buildNotebookDetail(notebookId);
    },

    async getSettings() {
        await wait(120);
        return buildSettingsView(mockState.user, mockState.settings);
    },

    async updateSettings(payload) {
        await wait(180);
        const nextSettings = {
            ...mockState.settings,
        };
        if (payload.clearApiKey) {
            nextSettings.apiKey = '';
        } else if (payload.apiKey) {
            nextSettings.apiKey = payload.apiKey;
        } else {
            nextSettings.apiKey = mockState.settings.apiKey;
        }
        if (payload.clearSearchApiKey) {
            nextSettings.searchApiKey = '';
        } else if (payload.searchApiKey) {
            nextSettings.searchApiKey = payload.searchApiKey;
        } else {
            nextSettings.searchApiKey = mockState.settings.searchApiKey;
        }
        if (payload.clearEmbeddingApiKey) {
            nextSettings.embeddingApiKey = '';
        } else if (payload.embeddingApiKey) {
            nextSettings.embeddingApiKey = payload.embeddingApiKey;
        } else {
            nextSettings.embeddingApiKey = mockState.settings.embeddingApiKey;
        }
        Object.entries(payload).forEach(([key, value]) => {
            if (
                key === 'apiKey'
                || key === 'clearApiKey'
                || key === 'searchApiKey'
                || key === 'clearSearchApiKey'
                || key === 'embeddingApiKey'
                || key === 'clearEmbeddingApiKey'
            ) return;
            nextSettings[key] = value;
        });
        mockState.settings = {
            ...nextSettings,
        };
        return buildSettingsView(mockState.user, mockState.settings);
    },

    async updateProfile(payload) {
        await wait(180);
        if (payload.username?.trim()) {
            mockState.user.name = payload.username.trim();
            mockState.settings.username = payload.username.trim();
        }

        const session = getStoredSession();
        if (session) {
            setStoredSession({
                ...session,
                user: clone(mockState.user),
            });
        }
        return clone(mockState.user);
    },

    async updatePassword({ oldPassword, newPassword, confirmPassword }) {
        await wait(180);
        if (!oldPassword || !newPassword || !confirmPassword) {
            throw new Error('请填写完整的密码信息');
        }
        if (newPassword !== confirmPassword) {
            throw new Error('两次输入的新密码不一致');
        }
        return { success: true };
    },

    async generateSummary({ notebookId, articleId }) {
        await wait(700);
        const notebook = getNotebookRecord(notebookId);
        const article = notebook.articles.find((item) => item.id === articleId);
        if (!article) throw new Error('未找到对应文章');
        return buildMockSummary(article);
    },

    async askAssistant({ notebookId, articleId, conversationId, message }) {
        await wait(850);
        const notebook = getNotebookRecord(notebookId);
        const article = notebook.articles.find((item) => item.id === articleId) || notebook.articles[0];
        return {
            conversationId: conversationId || `conv-${notebookId}`,
            route: 'RELATED_ARTICLES',
            reply: `基于《${article?.title || notebook.title}》的 mock 回复：已为“${message}”找到相关资料。正式后端会返回真实检索结果和引用。`,
            citations: article ? [{
                articleId: article.id,
                title: article.title,
                notebookId,
                notebookTitle: notebook.title,
                snippet: article.content?.slice(0, 120) || '',
                score: 0.12,
                matchedBy: ['lexical', 'semantic'],
            }] : [],
        };
    },

    async translateArticle({ notebookId, articleId, targetLanguage }) {
        await wait(800);
        const notebook = getNotebookRecord(notebookId);
        const article = notebook.articles.find((item) => item.id === articleId);
        if (!article) throw new Error('未找到对应文章');
        return buildMockTranslation(article, targetLanguage || mockState.settings.outputLanguage || '中文');
    },
};

const buildUrl = (path) => {
    if (/^https?:\/\//.test(path)) return path;
    const normalizedBase = runtimeConfig.apiBaseUrl.replace(/\/$/, '');
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    return `${normalizedBase}${normalizedPath}`;
};

const parseResponse = async (response) => {
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
        return response.json();
    }
    const text = await response.text();
    return text ? { message: text } : null;
};

const request = async (path, { method = 'GET', body, headers = {} } = {}) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), runtimeConfig.requestTimeoutMs);
    const session = getStoredSession();
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;

    try {
        const response = await fetch(buildUrl(path), {
            method,
            headers: {
                ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
                ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
                ...headers,
            },
            body: body ? (isFormData ? body : JSON.stringify(body)) : undefined,
            signal: controller.signal,
        });

        const payload = await parseResponse(response);
        if (!response.ok) {
            throw new Error(
                payload?.message
                || payload?.error?.message
                || `请求失败 (${response.status})`,
            );
        }

        return payload;
    } finally {
        clearTimeout(timeout);
    }
};

const normalizeSearchPayload = (payload) => {
    const item = payload?.item || {};
    return {
        searchSessionId: item.searchSessionId || payload?.searchSessionId || null,
        mode: item.mode || payload?.mode || 'auto',
        modeLabel: item.modeLabel || payload?.modeLabel || getSearchModeLabel(item.mode || payload?.mode || 'auto'),
        status: item.status || payload?.status || 'completed',
        execution: item.execution || payload?.execution || 'sync',
        items: payload?.items || item.items || [],
        meta: payload?.meta || item.meta || {},
        message: payload?.message || '',
    };
};

const pollSearchSession = async (fetchSession, { intervalMs = 1000, maxAttempts = 20 } = {}) => {
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
        const result = await fetchSession();
        if (result.status === 'completed' || result.status === 'failed') {
            return result;
        }
        await wait(intervalMs);
    }
    throw new Error('搜索任务超时，请稍后重试');
};

const backendProvider = {
    async login(credentials) {
        const payload = await request('/auth/login', { method: 'POST', body: credentials });
        const session = {
            token: payload.token,
            user: payload.user,
        };
        setStoredSession(session);
        return session;
    },

    async logout() {
        try {
            await request('/auth/logout', { method: 'POST' });
        } finally {
            clearStoredSession();
        }
        return { success: true };
    },

    async getCurrentUser() {
        const payload = await request('/auth/me');
        return payload.user;
    },

    async listNotebooks({ query = '' } = {}) {
        const queryString = query ? `?query=${encodeURIComponent(query)}` : '';
        const payload = await request(`/notebooks${queryString}`);
        return payload.items;
    },

    async createNotebook(notebook) {
        const payload = await request('/notebooks', {
            method: 'POST',
            body: notebook,
        });
        return payload.item;
    },

    async updateNotebook(notebookId, notebook) {
        const payload = await request(`/notebooks/${notebookId}`, {
            method: 'PATCH',
            body: notebook,
        });
        return payload.item;
    },

    async deleteNotebook(notebookId) {
        return request(`/notebooks/${notebookId}`, {
            method: 'DELETE',
        });
    },

    async getNotebookDetail(notebookId) {
        const payload = await request(`/notebooks/${notebookId}`);
        return payload.item;
    },

    async saveNote(notebookId, note) {
        const hasId = Boolean(note.id);
        const payload = await request(
            hasId
                ? `/notebooks/${notebookId}/notes/${note.id}`
                : `/notebooks/${notebookId}/notes`,
            {
                method: hasId ? 'PUT' : 'POST',
                body: note,
            },
        );
        return payload.item;
    },

    async deleteNote(notebookId, noteId) {
        await request(`/notebooks/${notebookId}/notes/${noteId}`, {
            method: 'DELETE',
        });
        return { success: true };
    },

    async getSearchSession({ notebookId, searchSessionId }) {
        const payload = await request(`/notebooks/${notebookId}/search-sessions/${searchSessionId}`);
        return normalizeSearchPayload(payload);
    },

    async searchSources({ notebookId, query, mode = 'auto', maxResults = 10, freshnessHours = 24 }) {
        const payload = await request(`/notebooks/${notebookId}/sources/search`, {
            method: 'POST',
            body: { query, mode, maxResults, freshnessHours },
        });
        const normalized = normalizeSearchPayload(payload);
        if (normalized.execution !== 'async' || !normalized.searchSessionId) {
            return normalized;
        }
        return pollSearchSession(
            () => backendProvider.getSearchSession({
                notebookId,
                searchSessionId: normalized.searchSessionId,
            }),
        );
    },

    async importSources({ notebookId, searchSessionId, searchResultIds }) {
        const payload = await request(`/notebooks/${notebookId}/sources/import`, {
            method: 'POST',
            body: { searchSessionId, searchResultIds },
        });
        return payload.item;
    },

    async createSource({ notebookId, sourceType, url, title, content }) {
        const payload = await request(`/notebooks/${notebookId}/sources`, {
            method: 'POST',
            body: { sourceType, url, title, content },
        });
        return payload.item;
    },

    async uploadFiles({ notebookId, files }) {
        const formData = new FormData();
        Array.from(files || []).forEach((file) => {
            formData.append('files', file);
        });
        const payload = await request(`/notebooks/${notebookId}/sources/upload`, {
            method: 'POST',
            body: formData,
        });
        return payload.item;
    },

    async getSettings() {
        const payload = await request('/settings');
        return payload.item;
    },

    async updateSettings(settings) {
        const payload = await request('/settings', {
            method: 'PUT',
            body: settings,
        });
        return payload.item;
    },

    async updateProfile(profile) {
        const payload = await request('/account/profile', {
            method: 'PATCH',
            body: profile,
        });
        const session = getStoredSession();
        if (session?.user) {
            setStoredSession({
                ...session,
                user: {
                    ...session.user,
                    ...payload.item,
                },
            });
        }
        return payload.item;
    },

    async updatePassword(passwordPayload) {
        return request('/account/password', {
            method: 'POST',
            body: passwordPayload,
        });
    },

    async generateSummary({ notebookId, articleId }) {
        const payload = await request(`/notebooks/${notebookId}/articles/${articleId}/summary`, {
            method: 'POST',
        });
        return payload.item || payload;
    },

    async askAssistant({ notebookId, articleId, conversationId, message }) {
        const payload = await request(`/notebooks/${notebookId}/chat`, {
            method: 'POST',
            body: { articleId, conversationId, message },
        });
        return payload.item || payload;
    },

    async translateArticle({ notebookId, articleId, targetLanguage }) {
        const payload = await request(`/notebooks/${notebookId}/articles/${articleId}/translate`, {
            method: 'POST',
            body: { targetLanguage },
        });
        return payload.item || payload;
    },
};

const provider = runtimeConfig.dataSource === 'api' ? backendProvider : mockProvider;

export const appApi = {
    runtime: runtimeConfig,
    auth: {
        login: provider.login,
        logout: provider.logout,
        getCurrentUser: provider.getCurrentUser,
    },
    notebooks: {
        list: provider.listNotebooks,
        create: provider.createNotebook,
        update: provider.updateNotebook,
        remove: provider.deleteNotebook,
        getDetail: provider.getNotebookDetail,
    },
    notes: {
        save: provider.saveNote,
        remove: provider.deleteNote,
    },
    sources: {
        search: provider.searchSources,
        getSession: provider.getSearchSession,
        importSelected: provider.importSources,
        create: provider.createSource,
        uploadFiles: provider.uploadFiles,
    },
    settings: {
        get: provider.getSettings,
        update: provider.updateSettings,
        updateProfile: provider.updateProfile,
        updatePassword: provider.updatePassword,
    },
    ai: {
        generateSummary: provider.generateSummary,
        askAssistant: provider.askAssistant,
        translateArticle: provider.translateArticle,
    },
};

export { getStoredSession };
