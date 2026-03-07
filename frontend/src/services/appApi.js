import { mockNotebooks, mockSearchResults, mockUser } from '../data/mockData';
import { runtimeConfig } from '../config/runtime';

const SESSION_STORAGE_KEY = 'notebooklm-session';

const DEFAULT_SETTINGS = {
    outputLanguage: mockUser.settings?.outputLanguage || '中文',
    themeColor: 'ocean',
    colorMode: mockUser.settings?.theme || 'light',
    modelProvider: '自定义',
    modelName: mockUser.settings?.model || 'gpt-4o',
    apiUrl: 'http://host.docker.internal:8317/v1/chat/completions',
    apiKey: '',
    username: mockUser.name,
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

const extractPlainExcerpt = (markdown) => markdown
    .replace(/^#.*$/gm, '')
    .replace(/[`*_>#-]/g, '')
    .split('\n')
    .map((line) => line.trim())
    .find(Boolean) || '暂无摘要内容';

const createImportedArticle = (source, index) => ({
    id: `art-import-${Date.now()}-${index}`,
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
    id: `art-upload-${Date.now()}-${index}`,
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
    id: `art-manual-${Date.now()}`,
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

const createMockState = () => ({
    user: clone(mockUser),
    settings: clone(DEFAULT_SETTINGS),
    notebooks: clone(mockNotebooks),
    notesByNotebookId: clone(DEFAULT_NOTES_BY_NOTEBOOK_ID),
    lastSearchResultsByNotebookId: {},
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

    async searchSources({ notebookId, query, searchMode, researchMode }) {
        await wait(900);
        if (!query?.trim()) {
            return { items: [], modeLabel: 'Web', query: '' };
        }

        const normalized = query.trim().toLowerCase();
        const matched = clone(mockSearchResults).filter((item) => (
            item.title.toLowerCase().includes(normalized)
            || item.description.toLowerCase().includes(normalized)
        ));
        const items = matched.length > 0 ? matched : clone(mockSearchResults);
        mockState.lastSearchResultsByNotebookId[notebookId] = items;

        const modeLabel = searchMode === 'research'
            ? (researchMode === 'deep' ? 'Deep Research' : 'Fast Research')
            : 'Web';

        return { items, modeLabel, query };
    },

    async importSources({ notebookId, sourceIds }) {
        await wait(260);
        const notebook = getNotebookRecord(notebookId);
        const searchResults = mockState.lastSearchResultsByNotebookId[notebookId] || [];
        const imported = searchResults
            .filter((item) => sourceIds.includes(item.id))
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
        return clone(mockState.settings);
    },

    async updateSettings(payload) {
        await wait(180);
        mockState.settings = {
            ...mockState.settings,
            ...payload,
        };
        return clone(mockState.settings);
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
            reply: `基于《${article?.title || notebook.title}》的 mock 回复：针对“${message}”，后端接入后这里会替换为真实带引用的问答结果。`,
        };
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

    async searchSources({ notebookId, query, searchMode, researchMode }) {
        return request(`/notebooks/${notebookId}/sources/search`, {
            method: 'POST',
            body: { query, searchMode, researchMode },
        });
    },

    async importSources({ notebookId, sourceIds }) {
        const payload = await request(`/notebooks/${notebookId}/sources/import`, {
            method: 'POST',
            body: { sourceIds },
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
        return request(`/notebooks/${notebookId}/articles/${articleId}/summary`, {
            method: 'POST',
        });
    },

    async askAssistant({ notebookId, articleId, conversationId, message }) {
        const payload = await request(`/notebooks/${notebookId}/chat`, {
            method: 'POST',
            body: { articleId, conversationId, message },
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
        getDetail: provider.getNotebookDetail,
    },
    notes: {
        save: provider.saveNote,
        remove: provider.deleteNote,
    },
    sources: {
        search: provider.searchSources,
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
    },
};

export { getStoredSession };
