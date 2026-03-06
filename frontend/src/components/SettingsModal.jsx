import { useState } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { mockUser, outputLanguages } from '../data/mockData';
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

export default function SettingsModal({ onClose }) {
    const { theme, setTheme } = useTheme();
    const [activeTab, setActiveTab] = useState('language');
    const [settings, setSettings] = useState({
        outputLanguage: mockUser.settings?.outputLanguage || '简体中文',
        themeColor: 'ocean',
        colorMode: theme === 'dark' ? 'dark' : 'light',
        modelProvider: '自定义',
        modelName: 'gpt-4o',
        apiUrl: 'http://host.docker.internal:8317/v1/chat/completions',
        apiKey: '',
        username: mockUser.name,
        oldPassword: '',
        newPassword: '',
        confirmPassword: '',
    });

    const update = (key, value) => setSettings(prev => ({ ...prev, [key]: value }));

    return (
        <div className="settings-overlay" onClick={onClose}>
            <div className="settings-modal animate-scale-in" onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className="settings-header">
                    <h3>设置</h3>
                    <button className="settings-close" onClick={onClose}>✕</button>
                </div>

                {/* Tabs */}
                <div className="settings-tabs">
                    {tabs.map(tab => (
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

                {/* Content */}
                <div className="settings-body">

                    {/* === 语言设置 === */}
                    {activeTab === 'language' && (
                        <div className="settings-tab-content">
                            <div className="settings-section">
                                <label className="settings-section-title">输出语言</label>
                                <p className="settings-hint">选择 AI 总结、翻译等功能的输出语言</p>
                                <div className="settings-select-wrapper">
                                    <select
                                        className="settings-select"
                                        value={settings.outputLanguage}
                                        onChange={(e) => update('outputLanguage', e.target.value)}
                                    >
                                        {outputLanguages.map(lang => (
                                            <option key={lang} value={lang}>{lang}</option>
                                        ))}
                                    </select>
                                    <span className="settings-select-arrow">▾</span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* === 外观设置 === */}
                    {activeTab === 'appearance' && (
                        <div className="settings-tab-content">
                            <div className="settings-section">
                                <label className="settings-section-title">主题色</label>
                                <div className="settings-color-grid">
                                    {themeColors.map(tc => (
                                        <button
                                            key={tc.id}
                                            className={`settings-color-btn ${settings.themeColor === tc.id ? 'active' : ''}`}
                                            onClick={() => update('themeColor', tc.id)}
                                            title={tc.label}
                                        >
                                            <span className="settings-color-dot" style={{ background: tc.color }} />
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
                                    ].map(m => (
                                        <button
                                            key={m.id}
                                            className={`settings-mode-btn ${settings.colorMode === m.id ? 'active' : ''}`}
                                            onClick={() => {
                                                update('colorMode', m.id);
                                                if (m.id !== 'auto') setTheme(m.id);
                                            }}
                                        >
                                            {m.icon} {m.label}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* === 模型设置 === */}
                    {activeTab === 'model' && (
                        <div className="settings-tab-content">
                            <div className="settings-section">
                                <label className="settings-section-title">模型提供商</label>
                                <div className="settings-select-wrapper">
                                    <select
                                        className="settings-select"
                                        value={settings.modelProvider}
                                        onChange={(e) => update('modelProvider', e.target.value)}
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
                                    onChange={(e) => update('modelName', e.target.value)}
                                />
                            </div>

                            <div className="settings-section">
                                <label className="settings-section-title">API 地址</label>
                                <input
                                    className="settings-input"
                                    placeholder="https://api.openai.com/v1"
                                    value={settings.apiUrl}
                                    onChange={(e) => update('apiUrl', e.target.value)}
                                />
                            </div>

                            <div className="settings-section">
                                <label className="settings-section-title">API Key</label>
                                <input
                                    className="settings-input"
                                    type="password"
                                    placeholder="sk-..."
                                    value={settings.apiKey}
                                    onChange={(e) => update('apiKey', e.target.value)}
                                />
                            </div>
                        </div>
                    )}

                    {/* === 账户设置 === */}
                    {activeTab === 'account' && (
                        <div className="settings-tab-content">
                            <div className="settings-section">
                                <label className="settings-section-title">用户名</label>
                                <input
                                    className="settings-input"
                                    value={settings.username}
                                    onChange={(e) => update('username', e.target.value)}
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
                                        onChange={(e) => update('oldPassword', e.target.value)}
                                    />
                                    <input
                                        className="settings-input"
                                        type="password"
                                        placeholder="新密码"
                                        value={settings.newPassword}
                                        onChange={(e) => update('newPassword', e.target.value)}
                                    />
                                    <input
                                        className="settings-input"
                                        type="password"
                                        placeholder="确认新密码"
                                        value={settings.confirmPassword}
                                        onChange={(e) => update('confirmPassword', e.target.value)}
                                    />
                                    <button className="settings-save-btn">保存密码</button>
                                </div>
                            </div>

                            <div className="settings-divider" />

                            <button className="settings-logout-btn" onClick={onClose}>
                                退出登录
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
