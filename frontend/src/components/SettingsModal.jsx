import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { outputLanguages } from '../data/mockData';
import { appApi } from '../services/appApi';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './SettingsModal.css';

const DEFAULT_PROVIDER_VALUE = '__default__';
const PROVIDER_OPENAI = 'openai';
const PROVIDER_ANTHROPIC = 'anthropic';
const PROVIDER_GEMINI = 'gemini';
const PROVIDER_OLLAMA = 'ollama';
const SEARCH_PROVIDER_EXA = 'exa';

const PROVIDER_LABELS = {
    [PROVIDER_OPENAI]: 'OpenAI',
    [PROVIDER_ANTHROPIC]: 'Anthropic',
    [PROVIDER_GEMINI]: 'Gemini',
    [PROVIDER_OLLAMA]: 'Ollama',
    [SEARCH_PROVIDER_EXA]: 'Exa',
};

const tabs = [
    { id: 'language', label: '语言', icon: '🌐' },
    { id: 'appearance', label: '外观', icon: '🎨' },
    { id: 'model', label: '聊天模型', icon: '🤖' },
    { id: 'embedding', label: 'Embedding', icon: '🧩' },
    { id: 'search', label: '搜索', icon: '🔎' },
    { id: 'account', label: '账户', icon: '👤' },
];

const themeColors = [
    { id: 'default', color: '#8b2c3b', label: '默认' },
    { id: 'forest', color: '#355F2E', label: '森林' },
    { id: 'ocean', color: '#133E87', label: '海洋' },
    { id: 'lavender', color: '#52357B', label: '薰衣草' },
    { id: 'mono', color: '#444444', label: '黑白' },
];
const latinFontOptions = [
    { id: 'times_new_roman', label: 'Times New Roman（默认）' },
    { id: 'georgia', label: 'Georgia' },
    { id: 'source_serif', label: 'Source Serif 4' },
    { id: 'source_sans', label: 'Source Sans 3' },
    { id: 'inter', label: 'Inter' },
    { id: 'jetbrains_mono', label: 'JetBrains Mono' },
];
const cjkFontOptions = [
    { id: 'source_han_serif', label: '思源宋体（默认）' },
    { id: 'source_han_sans', label: '思源黑体' },
    { id: 'songti', label: '宋体' },
    { id: 'kaiti', label: '楷体' },
    { id: 'yahei', label: '微软雅黑' },
];
const layoutModeOptions = [
    { id: 'triple', label: '三栏布局', desc: '左目录 + 正文 + 右侧栏' },
    { id: 'focus', label: '双栏布局', desc: '左目录 + 正文' },
    { id: 'reader', label: '阅读布局', desc: '仅正文' },
];

const createInitialSettings = () => ({
    outputLanguage: '简体中文',
    customSystemPrompt: '',
    answerLengthPreference: 'adaptive',
    themeColor: 'ocean',
    colorMode: 'light',
    fontFamily: 'sans',
    fontFamilyLatin: 'times_new_roman',
    fontFamilyCjk: 'source_han_serif',
    layoutMode: 'triple',
    modelProviderSelection: DEFAULT_PROVIDER_VALUE,
    modelProvider: 'ollama',
    modelName: 'qwen3.5:0.8b',
    apiUrl: 'http://127.0.0.1:11434',
    searchProviderSelection: DEFAULT_PROVIDER_VALUE,
    searchProvider: 'exa',
    preferredSites: [],
    usingDefaultModelConfig: true,
    defaultModelProvider: 'ollama',
    defaultModelName: 'qwen3.5:0.8b',
    defaultApiUrl: 'http://127.0.0.1:11434',
    usingDefaultSearchConfig: true,
    defaultSearchProvider: 'exa',
    embeddingProviderSelection: DEFAULT_PROVIDER_VALUE,
    embeddingProvider: 'ollama',
    embeddingModel: 'qwen3-embedding:0.6b',
    embeddingApiUrl: 'http://127.0.0.1:11434',
    usingDefaultEmbeddingConfig: true,
    defaultEmbeddingProvider: 'ollama',
    defaultEmbeddingModel: 'qwen3-embedding:0.6b',
    defaultEmbeddingApiUrl: 'http://127.0.0.1:11434',
    embeddingOutputDimensions: 1024,
    username: '',
    apiKey: '',
    searchApiKey: '',
    embeddingApiKey: '',
    hasApiKey: false,
    hasCustomApiKey: false,
    usingDefaultApiKey: false,
    apiKeyMasked: '',
    hasSearchApiKey: false,
    hasCustomSearchApiKey: false,
    usingDefaultSearchApiKey: false,
    searchApiKeyMasked: '',
    hasEmbeddingApiKey: false,
    hasCustomEmbeddingApiKey: false,
    usingDefaultEmbeddingApiKey: false,
    embeddingApiKeyMasked: '',
    clearApiKey: false,
    clearSearchApiKey: false,
    clearEmbeddingApiKey: false,
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
});

const getProviderLabel = (provider) => PROVIDER_LABELS[provider] || provider || '未配置';

const buildSystemDefaultLabel = (provider, modelName) => {
    const providerLabel = getProviderLabel(provider);
    return modelName
        ? `系统默认（${providerLabel} / ${modelName}）`
        : `系统默认（${providerLabel}）`;
};

const buildLegacyOption = (provider) => ({
    value: provider,
    label: `当前配置（${getProviderLabel(provider)}）`,
});

const getModelProviderOptions = (settings) => {
    const options = [
        {
            value: DEFAULT_PROVIDER_VALUE,
            label: buildSystemDefaultLabel(settings.defaultModelProvider, settings.defaultModelName),
        },
        { value: PROVIDER_OPENAI, label: 'OpenAI' },
        { value: PROVIDER_ANTHROPIC, label: 'Anthropic' },
        { value: PROVIDER_GEMINI, label: 'Gemini' },
    ];
    if (
        settings.modelProviderSelection !== DEFAULT_PROVIDER_VALUE
        && !options.some((option) => option.value === settings.modelProviderSelection)
    ) {
        options.push(buildLegacyOption(settings.modelProviderSelection));
    }
    return options;
};

const getEmbeddingProviderOptions = (settings) => {
    const options = [
        {
            value: DEFAULT_PROVIDER_VALUE,
            label: buildSystemDefaultLabel(settings.defaultEmbeddingProvider, settings.defaultEmbeddingModel),
        },
        { value: PROVIDER_OPENAI, label: 'OpenAI' },
    ];
    if (
        settings.embeddingProviderSelection !== DEFAULT_PROVIDER_VALUE
        && !options.some((option) => option.value === settings.embeddingProviderSelection)
    ) {
        options.push(buildLegacyOption(settings.embeddingProviderSelection));
    }
    return options;
};

const getSearchProviderOptions = (settings) => ([
    {
        value: DEFAULT_PROVIDER_VALUE,
        label: buildSystemDefaultLabel(settings.defaultSearchProvider),
    },
    { value: SEARCH_PROVIDER_EXA, label: 'Exa' },
]);

const MODEL_PROVIDER_PRESETS = {
    [PROVIDER_OPENAI]: {
        apiUrl: 'https://api.openai.com/v1',
        modelPlaceholder: '例如 gpt-4.1 / grok-4 / custom-model',
        apiUrlPlaceholder: 'https://api.openai.com/v1',
        apiKeyPlaceholder: 'sk-...',
    },
    [PROVIDER_ANTHROPIC]: {
        apiUrl: 'https://api.anthropic.com',
        modelPlaceholder: '例如 claude-sonnet-4-5',
        apiUrlPlaceholder: 'https://api.anthropic.com',
        apiKeyPlaceholder: 'sk-ant-...',
    },
    [PROVIDER_GEMINI]: {
        apiUrl: '',
        modelPlaceholder: '例如 gemini-2.5-flash',
        apiUrlPlaceholder: '可留空，默认官方 Gemini API',
        apiKeyPlaceholder: 'Gemini API Key',
    },
    [PROVIDER_OLLAMA]: {
        apiUrl: 'http://127.0.0.1:11434',
        modelPlaceholder: '例如 qwen3.5:0.8b',
        apiUrlPlaceholder: 'http://127.0.0.1:11434',
        apiKeyPlaceholder: 'Ollama 通常无需 API Key',
    },
};

const EMBEDDING_PROVIDER_PRESETS = {
    [PROVIDER_OPENAI]: {
        apiUrl: 'https://api.openai.com/v1',
        modelPlaceholder: '例如 text-embedding-3-large',
        apiUrlPlaceholder: 'https://api.openai.com/v1',
        apiKeyPlaceholder: 'sk-...',
    },
    [PROVIDER_OLLAMA]: {
        apiUrl: 'http://127.0.0.1:11434',
        modelPlaceholder: '例如 qwen3-embedding:0.6b',
        apiUrlPlaceholder: 'http://127.0.0.1:11434',
        apiKeyPlaceholder: '可留空',
    },
};

const getModelProviderPreset = (provider) => (
    MODEL_PROVIDER_PRESETS[provider] || MODEL_PROVIDER_PRESETS[PROVIDER_OPENAI]
);

const getEmbeddingProviderPreset = (provider) => (
    EMBEDDING_PROVIDER_PRESETS[provider] || EMBEDDING_PROVIDER_PRESETS[PROVIDER_OPENAI]
);

export default function SettingsModal({ onClose, initialTab = 'language' }) {
    const navigate = useNavigate();
    const {
        theme,
        setTheme,
        accentColor,
        setAccentColor,
        fontFamilyLatin,
        fontFamilyCjk,
        setFontFamilyLatin,
        setFontFamilyCjk,
    } = useTheme();
    const initialThemeRef = useRef(theme);
    const [activeTab, setActiveTab] = useState(initialTab);
    const [settings, setSettings] = useState(() => ({
        ...createInitialSettings(),
        themeColor: accentColor || 'ocean',
        colorMode: theme === 'auto' ? 'auto' : theme,
        fontFamilyLatin: fontFamilyLatin || 'times_new_roman',
        fontFamilyCjk: fontFamilyCjk || 'source_han_serif',
    }));
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [isTestingModel, setIsTestingModel] = useState(false);
    const [feedback, setFeedback] = useState('');
    const [modelTestFeedback, setModelTestFeedback] = useState('');
    const [modelTestStatus, setModelTestStatus] = useState('idle');
    const [avatarFile, setAvatarFile] = useState(null);
    const avatarInputRef = useRef(null);
    const modelProviderOptions = getModelProviderOptions(settings);
    const embeddingProviderOptions = getEmbeddingProviderOptions(settings);
    const searchProviderOptions = getSearchProviderOptions(settings);
    const modelProviderPreset = getModelProviderPreset(settings.modelProvider);
    const embeddingProviderPreset = getEmbeddingProviderPreset(settings.embeddingProvider);

    useEscapeToClose(onClose, !isSaving);

    useEffect(() => {
        let isMounted = true;

        const loadSettings = async () => {
            try {
                setIsLoading(true);
                setFeedback('');
                const [currentUser, currentSettings] = await Promise.all([
                    appApi.auth.getCurrentUser(),
                    appApi.settings.get(),
                ]);
                if (!isMounted) return;

                setSettings((prev) => ({
                    ...prev,
                    ...currentSettings,
                    modelProviderSelection: currentSettings.usingDefaultModelConfig ? DEFAULT_PROVIDER_VALUE : currentSettings.modelProvider,
                    searchProviderSelection: currentSettings.usingDefaultSearchConfig ? DEFAULT_PROVIDER_VALUE : currentSettings.searchProvider,
                    embeddingProviderSelection: currentSettings.usingDefaultEmbeddingConfig ? DEFAULT_PROVIDER_VALUE : currentSettings.embeddingProvider,
                    colorMode: initialThemeRef.current === 'auto' ? 'auto' : initialThemeRef.current,
                    fontFamilyLatin: currentSettings.fontFamilyLatin || prev.fontFamilyLatin || 'times_new_roman',
                    fontFamilyCjk: currentSettings.fontFamilyCjk || prev.fontFamilyCjk || 'source_han_serif',
                    layoutMode: currentSettings.layoutMode || prev.layoutMode || 'triple',
                    username: currentUser.name || currentSettings.username || '',
                    apiKey: '',
                    searchApiKey: '',
                    embeddingApiKey: '',
                    clearApiKey: false,
                    clearSearchApiKey: false,
                    clearEmbeddingApiKey: false,
                    oldPassword: '',
                    newPassword: '',
                    confirmPassword: '',
                }));
                if (currentSettings.themeColor) {
                    setAccentColor(currentSettings.themeColor);
                }
                setFontFamilyLatin(currentSettings.fontFamilyLatin || 'times_new_roman');
                setFontFamilyCjk(currentSettings.fontFamilyCjk || 'source_han_serif');
            } catch (err) {
                if (!isMounted) return;
                setFeedback(err.message || '加载设置失败');
            } finally {
                if (isMounted) setIsLoading(false);
            }
        };

        loadSettings();
        return () => {
            isMounted = false;
        };
    }, [setAccentColor, setFontFamilyCjk, setFontFamilyLatin]);

    useEffect(() => {
        setActiveTab(tabs.some((tab) => tab.id === initialTab) ? initialTab : 'language');
    }, [initialTab]);

    const update = (key, value) => {
        setFeedback('');
        setModelTestFeedback('');
        setModelTestStatus('idle');
        if (key === 'colorMode' && value) {
            setTheme(value);
        }
        if (key === 'fontFamilyLatin' && value) {
            setFontFamilyLatin(value);
        }
        if (key === 'fontFamilyCjk' && value) {
            setFontFamilyCjk(value);
        }
        if (key === 'layoutMode' && value && typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem('notebook.layout.preference', value);
            window.dispatchEvent(new CustomEvent('notebook-layout-mode-changed', { detail: { mode: value } }));
        }
        setSettings((prev) => {
            if (key === 'apiKey') {
                return { ...prev, apiKey: value, clearApiKey: false };
            }
            if (key === 'searchApiKey') {
                return { ...prev, searchApiKey: value, clearSearchApiKey: false };
            }
            if (key === 'embeddingApiKey') {
                return { ...prev, embeddingApiKey: value, clearEmbeddingApiKey: false };
            }
            if (key === 'clearApiKey') {
                return { ...prev, clearApiKey: value, apiKey: value ? '' : prev.apiKey };
            }
            if (key === 'clearSearchApiKey') {
                return { ...prev, clearSearchApiKey: value, searchApiKey: value ? '' : prev.searchApiKey };
            }
            if (key === 'clearEmbeddingApiKey') {
                return { ...prev, clearEmbeddingApiKey: value, embeddingApiKey: value ? '' : prev.embeddingApiKey };
            }
            if (key === 'modelProviderSelection') {
                if (value === DEFAULT_PROVIDER_VALUE) {
                    return {
                        ...prev,
                        modelProviderSelection: value,
                        modelProvider: prev.defaultModelProvider,
                        modelName: prev.defaultModelName,
                        apiUrl: prev.defaultApiUrl,
                        apiKey: '',
                        clearApiKey: false,
                    };
                }
                return {
                    ...prev,
                    modelProviderSelection: value,
                    modelProvider: value,
                    apiUrl: getModelProviderPreset(value).apiUrl,
                };
            }
            if (key === 'searchProviderSelection') {
                if (value === DEFAULT_PROVIDER_VALUE) {
                    return {
                        ...prev,
                        searchProviderSelection: value,
                        searchProvider: prev.defaultSearchProvider,
                        searchApiKey: '',
                        clearSearchApiKey: false,
                    };
                }
                return { ...prev, searchProviderSelection: value, searchProvider: value };
            }
            if (key === 'embeddingProviderSelection') {
                if (value === DEFAULT_PROVIDER_VALUE) {
                    return {
                        ...prev,
                        embeddingProviderSelection: value,
                        embeddingProvider: prev.defaultEmbeddingProvider,
                        embeddingModel: prev.defaultEmbeddingModel,
                        embeddingApiUrl: prev.defaultEmbeddingApiUrl,
                        embeddingApiKey: '',
                        clearEmbeddingApiKey: false,
                    };
                }
                return {
                    ...prev,
                    embeddingProviderSelection: value,
                    embeddingProvider: value,
                    embeddingApiUrl: getEmbeddingProviderPreset(value).apiUrl,
                };
            }
            if (key === 'preferredSitesText') {
                return {
                    ...prev,
                    preferredSites: value
                        .split('\n')
                        .map((line) => line.trim())
                        .filter(Boolean),
                };
            }
            if (key === 'colorMode') {
                return { ...prev, colorMode: value };
            }
            if (key === 'fontFamilyLatin') {
                return { ...prev, fontFamilyLatin: value };
            }
            if (key === 'fontFamilyCjk') {
                return { ...prev, fontFamilyCjk: value };
            }
            if (key === 'layoutMode') {
                return { ...prev, layoutMode: value };
            }
            return { ...prev, [key]: value };
        });
    };

    const buildSettingsPayload = () => {
        const payload = {
            outputLanguage: settings.outputLanguage,
            customSystemPrompt: settings.customSystemPrompt,
            answerLengthPreference: settings.answerLengthPreference,
            themeColor: settings.themeColor,
            colorMode: settings.colorMode,
            fontFamilyLatin: settings.fontFamilyLatin,
            fontFamilyCjk: settings.fontFamilyCjk,
            layoutMode: settings.layoutMode,
            preferredSites: settings.preferredSites,
        };

        if (settings.modelProviderSelection === DEFAULT_PROVIDER_VALUE) {
            payload.useDefaultModelConfig = true;
        } else {
            payload.modelProvider = settings.modelProvider;
            payload.modelName = settings.modelName;
            payload.apiUrl = settings.apiUrl;
            if (settings.apiKey.trim()) {
                payload.apiKey = settings.apiKey.trim();
            }
            if (settings.clearApiKey) {
                payload.clearApiKey = true;
            }
        }

        if (settings.searchProviderSelection === DEFAULT_PROVIDER_VALUE) {
            payload.useDefaultSearchConfig = true;
        } else {
            payload.searchProvider = settings.searchProvider;
            if (settings.searchApiKey.trim()) {
                payload.searchApiKey = settings.searchApiKey.trim();
            }
            if (settings.clearSearchApiKey) {
                payload.clearSearchApiKey = true;
            }
        }

        if (settings.embeddingProviderSelection === DEFAULT_PROVIDER_VALUE) {
            payload.useDefaultEmbeddingConfig = true;
        } else {
            payload.embeddingProvider = settings.embeddingProvider;
            payload.embeddingModel = settings.embeddingModel;
            payload.embeddingApiUrl = settings.embeddingApiUrl;
            if (settings.embeddingApiKey.trim()) {
                payload.embeddingApiKey = settings.embeddingApiKey.trim();
            }
            if (settings.clearEmbeddingApiKey) {
                payload.clearEmbeddingApiKey = true;
            }
        }

        return payload;
    };

    const buildModelTestPayload = () => {
        if (settings.modelProviderSelection === DEFAULT_PROVIDER_VALUE) {
            return { useDefaultModelConfig: true };
        }
        const payload = {
            modelProvider: settings.modelProvider,
            modelName: settings.modelName,
            apiUrl: settings.apiUrl,
        };
        const apiKey = settings.apiKey.trim();
        if (apiKey) {
            payload.apiKey = apiKey;
        }
        if (settings.clearApiKey) {
            payload.clearApiKey = true;
        }
        return payload;
    };

    const handleTestModelConnection = async () => {
        try {
            setIsTestingModel(true);
            setModelTestFeedback('');
            setModelTestStatus('idle');
            const result = await appApi.settings.testModelConnection(buildModelTestPayload());
            const latency = Number.isFinite(Number(result?.latencyMs)) ? `（${Math.round(Number(result.latencyMs))}ms）` : '';
            setModelTestStatus('success');
            setModelTestFeedback(`${result?.message || '连接成功'}${latency}`);
        } catch (err) {
            setModelTestStatus('error');
            setModelTestFeedback(err?.message || '模型连接测试失败');
        } finally {
            setIsTestingModel(false);
        }
    };

    const handleSave = async () => {
        try {
            setIsSaving(true);
            setFeedback('');

            if (activeTab === 'account') {
                let profile = await appApi.settings.updateProfile({ username: settings.username });
                if (avatarFile) {
                    profile = await appApi.settings.uploadAvatar(avatarFile);
                }
                setSettings((prev) => ({
                    ...prev,
                    username: profile.name || prev.username,
                }));
                if (settings.oldPassword || settings.newPassword || settings.confirmPassword) {
                    await appApi.settings.updatePassword({
                        oldPassword: settings.oldPassword,
                        newPassword: settings.newPassword,
                        confirmPassword: settings.confirmPassword,
                    });
                }
            } else {
                let nextSettings;
                const payload = buildSettingsPayload();
                try {
                    nextSettings = await appApi.settings.update(payload);
                } catch (err) {
                    if (activeTab === 'embedding' && err.code === 'embedding_reindex_confirmation_required') {
                        const affectedCount = err.meta?.affectedArticleCount || 0;
                        const confirmed = window.confirm(
                            `修改 Embedding 配置会触发向量重建，影响 ${affectedCount} 篇文章。重建期间仅支持关键词检索。是否继续？`,
                        );
                        if (!confirmed) {
                            setFeedback('已取消修改');
                            return;
                        }
                        nextSettings = await appApi.settings.update({
                            ...payload,
                            confirmEmbeddingReindex: true,
                        });
                    } else {
                        throw err;
                    }
                }
                setSettings((prev) => ({
                    ...prev,
                    ...nextSettings,
                    modelProviderSelection: nextSettings.usingDefaultModelConfig ? DEFAULT_PROVIDER_VALUE : nextSettings.modelProvider,
                    searchProviderSelection: nextSettings.usingDefaultSearchConfig ? DEFAULT_PROVIDER_VALUE : nextSettings.searchProvider,
                    embeddingProviderSelection: nextSettings.usingDefaultEmbeddingConfig ? DEFAULT_PROVIDER_VALUE : nextSettings.embeddingProvider,
                    apiKey: '',
                    searchApiKey: '',
                    embeddingApiKey: '',
                    clearApiKey: false,
                    clearSearchApiKey: false,
                    clearEmbeddingApiKey: false,
                }));
                if (nextSettings.colorMode) {
                    setTheme(nextSettings.colorMode);
                }
                setFontFamilyLatin(nextSettings.fontFamilyLatin || settings.fontFamilyLatin || 'times_new_roman');
                setFontFamilyCjk(nextSettings.fontFamilyCjk || settings.fontFamilyCjk || 'source_han_serif');
            }

            setSettings((prev) => ({
                ...prev,
                oldPassword: '',
                newPassword: '',
                confirmPassword: '',
            }));
            setAvatarFile(null);
            setFeedback('保存成功');
        } catch (err) {
            setFeedback(err.message || '保存设置失败');
        } finally {
            setIsSaving(false);
        }
    };

    const handleLogout = async () => {
        await appApi.auth.logout();
        onClose();
        navigate('/login');
    };

    return (
        <div className="settings-overlay" onClick={onClose}>
            <div className="settings-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <div className="settings-header">
                    <h3>设置</h3>
                    <button className="settings-close" onClick={onClose}>✕</button>
                </div>

                <div className="settings-tabs">
                    {tabs.map((tab) => (
                        <button
                            key={tab.id}
                            className={`settings-tab ${activeTab === tab.id ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            <span className="settings-tab-icon">{tab.icon}</span>
                            <span>{tab.label}</span>
                        </button>
                    ))}
                </div>

                <div className="settings-body">
                    {isLoading ? (
                        <div className="settings-tab-content">
                            <div className="settings-loading">
                                <span className="ui-spinner-ring" aria-hidden="true" />
                                <p className="settings-hint">正在加载设置...</p>
                            </div>
                        </div>
                    ) : (
                        <>
                            {activeTab === 'language' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">输出语言</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.outputLanguage}
                                                onChange={(event) => update('outputLanguage', event.target.value)}
                                            >
                                                {outputLanguages.map((lang) => (
                                                    <option key={lang} value={lang}>{lang}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">自定义系统 Prompt</label>
                                        <textarea className="settings-input" rows={4} value={settings.customSystemPrompt} onChange={(event) => update('customSystemPrompt', event.target.value)} placeholder="例如：请始终使用简体中文，回答保持简洁" />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">回答长度偏好</label>
                                        <div className="settings-select-wrapper">
                                            <select className="settings-select" value={settings.answerLengthPreference} onChange={(event) => update('answerLengthPreference', event.target.value)}>
                                                <option value="concise">简洁</option>
                                                <option value="detailed">详细</option>
                                                <option value="adaptive">自适应</option>
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>
                                </div>
                            )}

                            {activeTab === 'appearance' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">主题色</label>
                                        <div className="settings-color-grid">
                                            {themeColors.map((themeOption) => (
                                                <button
                                                    key={themeOption.id}
                                                    className={`settings-color-btn ${settings.themeColor === themeOption.id ? 'active' : ''}`}
                                                    onClick={() => {
                                                        update('themeColor', themeOption.id);
                                                        setAccentColor(themeOption.id);
                                                    }}
                                                    title={themeOption.label}
                                                >
                                                    <span className="settings-color-dot" style={{ background: themeOption.color }} />
                                                </button>
                                            ))}
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">颜色模式</label>
                                        <div className="settings-mode-group">
                                            {[
                                                { id: 'light', label: '亮色', icon: '☀️' },
                                                { id: 'dark', label: '暗色', icon: '🌙' },
                                                { id: 'auto', label: '自动', icon: '◐' },
                                            ].map((modeOption) => (
                                                <button
                                                    key={modeOption.id}
                                                    className={`settings-mode-btn ${settings.colorMode === modeOption.id ? 'active' : ''}`}
                                                    onClick={() => update('colorMode', modeOption.id)}
                                                >
                                                    {modeOption.icon} {modeOption.label}
                                                </button>
                                            ))}
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">英文字体</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.fontFamilyLatin || 'times_new_roman'}
                                                onChange={(event) => update('fontFamilyLatin', event.target.value)}
                                            >
                                                {latinFontOptions.map((option) => (
                                                    <option key={option.id} value={option.id}>{option.label}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">中文字体</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.fontFamilyCjk || 'source_han_serif'}
                                                onChange={(event) => update('fontFamilyCjk', event.target.value)}
                                            >
                                                {cjkFontOptions.map((option) => (
                                                    <option key={option.id} value={option.id}>{option.label}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">默认页面布局</label>
                                        <div className="settings-layout-group">
                                            {layoutModeOptions.map((option) => (
                                                <button
                                                    key={option.id}
                                                    type="button"
                                                    className={`settings-layout-btn ${settings.layoutMode === option.id ? 'active' : ''}`}
                                                    onClick={() => update('layoutMode', option.id)}
                                                >
                                                    <span className="settings-layout-title">{option.label}</span>
                                                    <span className="settings-layout-desc">{option.desc}</span>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {activeTab === 'model' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">模型提供商</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.modelProviderSelection}
                                                onChange={(event) => update('modelProviderSelection', event.target.value)}
                                            >
                                                {modelProviderOptions.map((option) => (
                                                    <option key={option.value} value={option.value}>{option.label}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">模型名称</label>
                                        <input
                                            className="settings-input"
                                            placeholder={modelProviderPreset.modelPlaceholder}
                                            value={settings.modelName}
                                            disabled={settings.modelProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('modelName', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">API 地址</label>
                                        <input
                                            className="settings-input"
                                            placeholder={modelProviderPreset.apiUrlPlaceholder}
                                            value={settings.apiUrl}
                                            disabled={settings.modelProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('apiUrl', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">API Key</label>
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.modelProvider === PROVIDER_OLLAMA ? modelProviderPreset.apiKeyPlaceholder : (settings.hasApiKey ? '留空则不修改，输入新值则替换' : modelProviderPreset.apiKeyPlaceholder)}
                                            value={settings.apiKey}
                                            disabled={settings.modelProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('apiKey', event.target.value)}
                                        />
                                        {settings.hasCustomApiKey && settings.modelProviderSelection !== DEFAULT_PROVIDER_VALUE && (
                                            <button
                                                className="settings-save-btn"
                                                onClick={() => update('clearApiKey', !settings.clearApiKey)}
                                            >
                                                {settings.clearApiKey ? '保留自定义 Key' : '移除自定义 Key'}
                                            </button>
                                        )}
                                    </div>

                                    <div className="settings-section settings-inline-actions">
                                        <button
                                            type="button"
                                            className="settings-save-btn"
                                            onClick={handleTestModelConnection}
                                            disabled={isTestingModel || isLoading || isSaving}
                                        >
                                            {isTestingModel ? '测试中...' : '测试连接'}
                                        </button>
                                        {modelTestFeedback ? (
                                            <span className={`settings-inline-feedback ${modelTestStatus === 'error' ? 'error' : 'success'}`}>
                                                {modelTestFeedback}
                                            </span>
                                        ) : null}
                                    </div>
                                </div>
                            )}

                            {activeTab === 'embedding' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding Provider</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.embeddingProviderSelection}
                                                onChange={(event) => update('embeddingProviderSelection', event.target.value)}
                                            >
                                                {embeddingProviderOptions.map((option) => (
                                                    <option key={option.value} value={option.value}>{option.label}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding 模型</label>
                                        <input
                                            className="settings-input"
                                            placeholder={embeddingProviderPreset.modelPlaceholder}
                                            value={settings.embeddingModel}
                                            disabled={settings.embeddingProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('embeddingModel', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding API 地址</label>
                                        <input
                                            className="settings-input"
                                            placeholder={embeddingProviderPreset.apiUrlPlaceholder}
                                            value={settings.embeddingApiUrl}
                                            disabled={settings.embeddingProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('embeddingApiUrl', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding API Key</label>
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.embeddingProvider === PROVIDER_OLLAMA ? embeddingProviderPreset.apiKeyPlaceholder : (settings.hasEmbeddingApiKey ? '留空则不修改，输入新值则替换' : embeddingProviderPreset.apiKeyPlaceholder)}
                                            value={settings.embeddingApiKey}
                                            disabled={settings.embeddingProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('embeddingApiKey', event.target.value)}
                                        />
                                        {settings.hasCustomEmbeddingApiKey && settings.embeddingProviderSelection !== DEFAULT_PROVIDER_VALUE && (
                                            <button
                                                className="settings-save-btn"
                                                onClick={() => update('clearEmbeddingApiKey', !settings.clearEmbeddingApiKey)}
                                            >
                                                {settings.clearEmbeddingApiKey ? '保留自定义 Key' : '移除自定义 Key'}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}

                            {activeTab === 'search' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">搜索引擎 Provider</label>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.searchProviderSelection}
                                                onChange={(event) => update('searchProviderSelection', event.target.value)}
                                            >
                                                {searchProviderOptions.map((option) => (
                                                    <option key={option.value} value={option.value}>{option.label}</option>
                                                ))}
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>
                                    <div className="settings-section">
                                        <label className="settings-section-title">偏好站点</label>
                                        <textarea
                                            className="settings-input"
                                            rows={5}
                                            value={(settings.preferredSites || []).join('\n')}
                                            onChange={(event) => update('preferredSitesText', event.target.value)}
                                            placeholder={'arxiv.org\nopenai.com\ndocs.anthropic.com'}
                                        />
                                    </div>
                                    <div className="settings-section">
                                        <label className="settings-section-title">Exa API Key</label>
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.hasSearchApiKey ? '留空则不修改，输入新值则替换' : 'exa_...'}
                                            value={settings.searchApiKey}
                                            disabled={settings.searchProviderSelection === DEFAULT_PROVIDER_VALUE}
                                            onChange={(event) => update('searchApiKey', event.target.value)}
                                        />
                                        {settings.hasCustomSearchApiKey && settings.searchProviderSelection !== DEFAULT_PROVIDER_VALUE && (
                                            <button
                                                className="settings-save-btn"
                                                onClick={() => update('clearSearchApiKey', !settings.clearSearchApiKey)}
                                            >
                                                {settings.clearSearchApiKey ? '保留自定义搜索 Key' : '移除自定义搜索 Key'}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}

                            {activeTab === 'account' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">用户名</label>
                                        <input
                                            className="settings-input"
                                            value={settings.username}
                                            onChange={(event) => update('username', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">头像上传</label>
                                        <div className="settings-avatar-upload">
                                            <input
                                                ref={avatarInputRef}
                                                type="file"
                                                accept="image/*"
                                                className="settings-avatar-input"
                                                onChange={(event) => setAvatarFile(event.target.files?.[0] || null)}
                                            />
                                            <button
                                                type="button"
                                                className="settings-avatar-trigger"
                                                onClick={() => avatarInputRef.current?.click()}
                                            >
                                                {avatarFile ? '重新选择' : '上传头像'}
                                            </button>
                                            <span className={`settings-avatar-filename ${avatarFile ? 'has-file' : ''}`}>
                                                {avatarFile?.name || '未选择文件'}
                                            </span>
                                        </div>
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">修改密码</label>
                                        <div className="settings-password-fields">
                                            <input
                                                className="settings-input"
                                                type="password"
                                                placeholder="当前密码"
                                                value={settings.oldPassword}
                                                onChange={(event) => update('oldPassword', event.target.value)}
                                            />
                                            <input
                                                className="settings-input"
                                                type="password"
                                                placeholder="新密码"
                                                value={settings.newPassword}
                                                onChange={(event) => update('newPassword', event.target.value)}
                                            />
                                            <input
                                                className="settings-input"
                                                type="password"
                                                placeholder="确认新密码"
                                                value={settings.confirmPassword}
                                                onChange={(event) => update('confirmPassword', event.target.value)}
                                            />
                                        </div>
                                    </div>

                                    <div className="settings-divider" />

                                    <button className="settings-logout-btn" onClick={handleLogout}>
                                        退出登录
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </div>

                <div className="settings-footer">
                    <span className="settings-status">{feedback}</span>
                    <div className="settings-footer-actions">
                        <button className="settings-footer-secondary" onClick={onClose} disabled={isSaving}>
                            关闭
                        </button>
                        <button className="settings-footer-primary" onClick={handleSave} disabled={isSaving || isLoading}>
                            {isSaving ? '保存中...' : '保存全部设置'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
