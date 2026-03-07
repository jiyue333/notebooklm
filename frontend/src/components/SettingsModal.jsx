import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { outputLanguages } from '../data/mockData';
import { appApi } from '../services/appApi';
import './SettingsModal.css';

const tabs = [
    { id: 'language', label: '语言', icon: '🌐' },
    { id: 'appearance', label: '外观', icon: '🎨' },
    { id: 'model', label: '模型', icon: '🤖' },
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
    modelProvider: '自定义',
    modelName: 'gpt-4o',
    apiUrl: 'http://host.docker.internal:8317/v1/chat/completions',
    apiKey: '',
    username: '',
    oldPassword: '',
    newPassword: '',
    confirmPassword: '',
});

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
        setSettings((prev) => ({ ...prev, [key]: value }));
    };

    const buildSettingsPayload = () => {
        if (activeTab === 'language') {
            return { outputLanguage: settings.outputLanguage };
        }
        if (activeTab === 'appearance') {
            return { themeColor: settings.themeColor, colorMode: settings.colorMode };
        }
        return {
            modelProvider: settings.modelProvider,
            modelName: settings.modelName,
            apiUrl: settings.apiUrl,
            apiKey: settings.apiKey,
        };
    };

    const handleSave = async () => {
        try {
            setIsSaving(true);
            setFeedback('');

            if (activeTab === 'account') {
                await appApi.settings.updateProfile({ username: settings.username });
                if (settings.oldPassword || settings.newPassword || settings.confirmPassword) {
                    await appApi.settings.updatePassword({
                        oldPassword: settings.oldPassword,
                        newPassword: settings.newPassword,
                        confirmPassword: settings.confirmPassword,
                    });
                }
            } else {
                await appApi.settings.update(buildSettingsPayload());
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
                                        <div className="settings-select-wrapper">
                                            <select
                                                className="settings-select"
                                                value={settings.modelProvider}
                                                onChange={(event) => update('modelProvider', event.target.value)}
                                            >
                                                <option value="自定义">自定义</option>
                                                <option value="OpenAI">OpenAI</option>
                                                <option value="Anthropic">Anthropic</option>
                                                <option value="Google">Google</option>
                                                <option value="Ollama">Ollama</option>
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
                                            placeholder="https://api.openai.com/v1"
                                            value={settings.apiUrl}
                                            onChange={(event) => update('apiUrl', event.target.value)}
                                        />
                                    </div>

                                    <div className="settings-section">
                                        <label className="settings-section-title">API Key</label>
                                        <input
                                            className="settings-input"
                                            type="password"
                                            placeholder="sk-..."
                                            value={settings.apiKey}
                                            onChange={(event) => update('apiKey', event.target.value)}
                                        />
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
