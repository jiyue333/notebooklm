import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { outputLanguages } from '../data/mockData';
import { appApi } from '../services/appApi';
import './SettingsModal.css';

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

const createInitialSettings = () => ({
    outputLanguage: '简体中文',
    themeColor: 'ocean',
    colorMode: 'light',
    modelProvider: 'openai_compatible',
    modelName: 'gpt-4o',
    apiUrl: 'http://host.docker.internal:8317/v1/chat/completions',
    searchProvider: 'exa',
    embeddingProvider: 'openai_compatible',
    embeddingModel: 'text-embedding-3-large',
    embeddingApiUrl: 'https://api.openai.com/v1',
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

const modelProviderOptions = [
    { value: 'openai_compatible', label: 'OpenAI兼容' },
    { value: 'ollama', label: 'Ollama' },
];

const embeddingProviderOptions = [
    { value: 'openai_compatible', label: 'OpenAI兼容' },
    { value: 'ollama', label: 'Ollama' },
];

export default function SettingsModal({ onClose }) {
    const navigate = useNavigate();
    const { theme, setTheme } = useTheme();
    const [activeTab, setActiveTab] = useState('language');
    const [settings, setSettings] = useState(() => ({
        ...createInitialSettings(),
        colorMode: theme === 'dark' ? 'dark' : 'light',
    }));
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [feedback, setFeedback] = useState('');

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
    }, []);

    const update = (key, value) => {
        setFeedback('');
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
            return { ...prev, [key]: value };
        });
    };

    const buildSettingsPayload = () => {
        if (activeTab === 'language') {
            return { outputLanguage: settings.outputLanguage };
        }
        if (activeTab === 'appearance') {
            return { themeColor: settings.themeColor, colorMode: settings.colorMode };
        }
        if (activeTab === 'search') {
            return {
                searchProvider: settings.searchProvider,
                ...(settings.searchApiKey.trim() ? { searchApiKey: settings.searchApiKey.trim() } : {}),
                ...(settings.clearSearchApiKey ? { clearSearchApiKey: true } : {}),
            };
        }
        if (activeTab === 'embedding') {
            return {
                embeddingProvider: settings.embeddingProvider,
                embeddingModel: settings.embeddingModel,
                embeddingApiUrl: settings.embeddingApiUrl,
                ...(settings.embeddingApiKey.trim() ? { embeddingApiKey: settings.embeddingApiKey.trim() } : {}),
                ...(settings.clearEmbeddingApiKey ? { clearEmbeddingApiKey: true } : {}),
            };
        }
        return {
            modelProvider: settings.modelProvider,
            modelName: settings.modelName,
            apiUrl: settings.apiUrl,
            ...(settings.apiKey.trim() ? { apiKey: settings.apiKey.trim() } : {}),
            ...(settings.clearApiKey ? { clearApiKey: true } : {}),
        };
    };

    const handleSave = async () => {
        try {
            setIsSaving(true);
            setFeedback('');

            if (activeTab === 'account') {
                const profile = await appApi.settings.updateProfile({ username: settings.username });
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
                const nextSettings = await appApi.settings.update(buildSettingsPayload());
                setSettings((prev) => ({
                    ...prev,
                    ...nextSettings,
                    apiKey: '',
                    searchApiKey: '',
                    embeddingApiKey: '',
                    clearApiKey: false,
                    clearSearchApiKey: false,
                    clearEmbeddingApiKey: false,
                }));
                if (activeTab === 'appearance' && settings.colorMode !== 'auto') {
                    setTheme(settings.colorMode);
                }
            }

            setSettings((prev) => ({
                ...prev,
                oldPassword: '',
                newPassword: '',
                confirmPassword: '',
            }));
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
                            <p className="settings-hint">正在加载设置...</p>
                        </div>
                    ) : (
                        <>
                            {activeTab === 'language' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">输出语言</label>
                                        <p className="settings-hint">选择 AI 总结、翻译等功能的输出语言</p>
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
                                                    onClick={() => update('themeColor', themeOption.id)}
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
                                                    onClick={() => {
                                                        update('colorMode', modeOption.id);
                                                        if (modeOption.id !== 'auto') setTheme(modeOption.id);
                                                    }}
                                                >
                                                    {modeOption.icon} {modeOption.label}
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
                                        <p className="settings-hint">聊天和摘要统一使用用户配置的模型；如果你没有填自定义 Key，后端会尝试使用系统默认 Key。</p>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.modelProvider}
                                                onChange={(event) => update('modelProvider', event.target.value)}
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
                                            placeholder="例如 gpt-4o"
                                            value={settings.modelName}
                                            onChange={(event) => update('modelName', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">API 地址</label>
                                        <input
                                            className="settings-input"
                                            placeholder={settings.modelProvider === 'ollama' ? 'http://127.0.0.1:11434' : 'https://api.openai.com/v1'}
                                            value={settings.apiUrl}
                                            onChange={(event) => update('apiUrl', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">API Key</label>
                                        {settings.usingDefaultApiKey && !settings.hasCustomApiKey && !settings.clearApiKey && (
                                            <p className="settings-hint">当前使用系统默认聊天 Key。留空则继续使用默认值，输入新值可覆盖。</p>
                                        )}
                                        {settings.hasCustomApiKey && !settings.clearApiKey && (
                                            <p className="settings-hint">已保存 Key：{settings.apiKeyMasked || '已配置'}。留空则保持不变。</p>
                                        )}
                                        {settings.clearApiKey && (
                                            <p className="settings-hint">当前将移除自定义聊天 Key，并回退到系统默认 Key（如果有）。</p>
                                        )}
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.modelProvider === 'ollama' ? 'Ollama 通常无需 API Key' : (settings.hasApiKey ? '留空则不修改，输入新值则替换' : 'sk-...')}
                                            value={settings.apiKey}
                                            onChange={(event) => update('apiKey', event.target.value)}
                                        />
                                        {settings.hasCustomApiKey && (
                                            <button
                                                className="settings-save-btn"
                                                onClick={() => update('clearApiKey', !settings.clearApiKey)}
                                            >
                                                {settings.clearApiKey ? '保留自定义 Key' : '移除自定义 Key'}
                                            </button>
                                        )}
                                    </div>
                                </div>
                            )}

                            {activeTab === 'embedding' && (
                                <div className="settings-tab-content">
                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding Provider</label>
                                        <p className="settings-hint">检索向量使用独立配置。支持 OpenAI 兼容接口，也支持直接连 Ollama。</p>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.embeddingProvider}
                                                onChange={(event) => update('embeddingProvider', event.target.value)}
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
                                            placeholder={settings.embeddingProvider === 'ollama' ? '例如 nomic-embed-text' : '例如 text-embedding-3-large'}
                                            value={settings.embeddingModel}
                                            onChange={(event) => update('embeddingModel', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding API 地址</label>
                                        <input
                                            className="settings-input"
                                            placeholder={settings.embeddingProvider === 'ollama' ? 'http://127.0.0.1:11434' : 'https://api.openai.com/v1'}
                                            value={settings.embeddingApiUrl}
                                            onChange={(event) => update('embeddingApiUrl', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">Embedding API Key</label>
                                        {settings.embeddingProvider === 'ollama' && (
                                            <p className="settings-hint">Ollama 原生模式通常不需要 API Key。</p>
                                        )}
                                        {settings.usingDefaultEmbeddingApiKey && !settings.hasCustomEmbeddingApiKey && !settings.clearEmbeddingApiKey && settings.embeddingProvider !== 'ollama' && (
                                            <p className="settings-hint">当前使用系统默认 embedding Key。留空则继续使用默认值，输入新值可覆盖。</p>
                                        )}
                                        {settings.hasCustomEmbeddingApiKey && !settings.clearEmbeddingApiKey && (
                                            <p className="settings-hint">已保存 Key：{settings.embeddingApiKeyMasked || '已配置'}。留空则保持不变。</p>
                                        )}
                                        {settings.clearEmbeddingApiKey && (
                                            <p className="settings-hint">当前将移除自定义 embedding Key，并回退到系统默认 Key（如果有）。</p>
                                        )}
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.embeddingProvider === 'ollama' ? '可留空' : (settings.hasEmbeddingApiKey ? '留空则不修改，输入新值则替换' : 'sk-...')}
                                            value={settings.embeddingApiKey}
                                            onChange={(event) => update('embeddingApiKey', event.target.value)}
                                        />
                                        {settings.hasCustomEmbeddingApiKey && (
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
                                        <p className="settings-hint">当前搜索来源发现统一走后端 Search Provider。现阶段只开放 Exa，可使用系统默认 Key，也可以配置用户自己的 Key。</p>
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.searchProvider}
                                                onChange={(event) => update('searchProvider', event.target.value)}
                                            >
                                                <option value="exa">Exa</option>
                                            </select>
                                            <span className="settings-select-arrow">▾</span>
                                        </div>
                                    </div>
                                    <div className="settings-section">
                                        <label className="settings-section-title">Exa API Key</label>
                                        {settings.usingDefaultSearchApiKey && !settings.hasCustomSearchApiKey && !settings.clearSearchApiKey && (
                                            <p className="settings-hint">当前使用系统默认 Exa Key。留空则继续使用默认值，输入新值可覆盖。</p>
                                        )}
                                        {settings.hasCustomSearchApiKey && !settings.clearSearchApiKey && (
                                            <p className="settings-hint">已保存 Key：{settings.searchApiKeyMasked || '已配置'}。留空则保持不变。</p>
                                        )}
                                        {settings.clearSearchApiKey && (
                                            <p className="settings-hint">当前将移除自定义 Exa Key，并回退到系统默认 Key（如果有）。</p>
                                        )}
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder={settings.hasSearchApiKey ? '留空则不修改，输入新值则替换' : 'exa_...'}
                                            value={settings.searchApiKey}
                                            onChange={(event) => update('searchApiKey', event.target.value)}
                                        />
                                        {settings.hasCustomSearchApiKey && (
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
                            {isSaving ? '保存中...' : '保存更改'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
