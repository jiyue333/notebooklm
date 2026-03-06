import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../contexts/ThemeContext';
import { mockNotebooks, mockUser } from '../data/mockData';
import SettingsModal from '../components/SettingsModal';
import './HomePage.css';

export default function HomePage() {
    const navigate = useNavigate();
    const { theme, toggleTheme } = useTheme();
    const [showSettings, setShowSettings] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    const filteredNotebooks = mockNotebooks.filter(nb =>
        nb.title.toLowerCase().includes(searchQuery.toLowerCase())
    );

    return (
        <div className="home-page">
            {/* Top Bar */}
            <header className="home-topbar">
                <div className="home-topbar-left">
                    <div className="home-logo">
                        <svg width="28" height="28" viewBox="0 0 48 48" fill="none">
                            <rect width="48" height="48" rx="12" fill="var(--accent-color)" />
                            <path d="M14 16h20v2H14zm0 6h20v2H14zm0 6h14v2H14zm0 6h18v2H14z" fill="white" opacity="0.9" />
                        </svg>
                        <span className="home-logo-text">NotebookLM</span>
                    </div>
                </div>

                <div className="home-topbar-center">
                    <div className="home-search-wrapper">
                        <span className="home-search-icon">🔍</span>
                        <input
                            className="input home-search-input"
                            placeholder="搜索笔记本..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                        />
                    </div>
                </div>

                <div className="home-topbar-right">
                    <button className="btn-icon" onClick={toggleTheme} title="切换主题">
                        {theme === 'light' ? '🌙' : '☀️'}
                    </button>
                    <button className="btn-icon" onClick={() => setShowSettings(true)} title="设置">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
                            <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.64-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.57 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
                        </svg>
                    </button>
                    <div className="home-avatar">
                        {mockUser.name.charAt(0)}
                    </div>
                </div>
            </header>

            {/* Main Content */}
            <main className="home-main">
                <div className="home-content">
                    <h2 className="home-section-title">最近打开过的笔记本</h2>

                    <div className="home-grid">
                        {/* Create New */}
                        <div className="home-card home-card-new animate-fade-in-up" onClick={() => { }}>
                            <div className="home-card-new-inner">
                                <div className="home-card-new-icon"><span>+</span></div>
                                <span className="home-card-new-text">新建笔记本</span>
                            </div>
                        </div>

                        {filteredNotebooks.map((nb, index) => (
                            <div
                                key={nb.id}
                                className="home-card animate-fade-in-up"
                                style={{ animationDelay: `${(index + 1) * 0.06}s` }}
                                onClick={() => navigate(`/notebook/${nb.id}`)}
                            >
                                <div className="home-card-header" style={{ background: nb.color }}>
                                    <span className="home-card-emoji">{nb.emoji}</span>
                                    <button
                                        className="home-card-menu"
                                        onClick={(e) => { e.stopPropagation(); }}
                                    >⋮</button>
                                </div>
                                <div className="home-card-body">
                                    <h3 className="home-card-title">{nb.title}</h3>
                                    <p className="home-card-meta">{nb.date} · {nb.sourceCount} 个来源</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </main>

            {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
        </div>
    );
}
