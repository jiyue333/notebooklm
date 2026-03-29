import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppLogo from '../components/common/AppLogo';
import AccountMenu from '../components/common/AccountMenu';
import EmptyState from '../components/common/EmptyState';
import ErrorBanner from '../components/common/ErrorBanner';
import Spinner from '../components/common/Spinner';
import { useToast } from '../components/common/useToast';
import { getLogoOptions } from '../components/common/logoOptions';
import { useTheme } from '../contexts/useTheme';
import { appApi, clearStoredSession, getStoredSession, isAuthError } from '../services/appApi';
import SettingsModal from '../components/SettingsModal';
import NotebookModal from '../components/NotebookModal';
import FeedWorkspaceModal from '../components/FeedWorkspaceModal';
import './HomePage.css';

const LOGO_STORAGE_KEY = '[REDACTED]-logo-option';
const RECENT_NOTEBOOK_LIMIT = 4;
const Hc = {
    theme: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 8.69V4h-4.69L12 .69 8.69 4H4v4.69L.69 12 4 15.31V20h4.69L12 23.31 15.31 20H20v-4.69L23.31 12 20 8.69zM12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-10c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z" /></svg>,
    settings: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" /></svg>,
    layout: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 3h18v18H3V3zm2 2v14h14V5H5zm2 2h4v4H7V7zm0 6h4v4H7v-4zm6-6h4v10h-4V7z" /></svg>,
    notebook: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 2h9a3 3 0 0 1 3 3v14a1 1 0 0 1-1.6.8L13 17.4l-3.4 2.4A1 1 0 0 1 8 19V5a3 3 0 0 0-2-2.82V2Zm4 4h5v2h-5V6Zm0 4h5v2h-5v-2Z" /><path d="M4 3.5A1.5 1.5 0 0 1 5.5 2h.5v20h-.5A1.5 1.5 0 0 1 4 20.5v-17Z" /></svg>,
    feed: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6.18 17.82a2.18 2.18 0 1 1 0-4.36 2.18 2.18 0 0 1 0 4.36ZM4 4v3a13 13 0 0 1 13 13h3A16 16 0 0 0 4 4Zm0 6v3a7 7 0 0 1 7 7h3a10 10 0 0 0-10-10Z" /></svg>,
};

function getStoredLogoOption() {
    if (typeof window === 'undefined' || !window.localStorage) return 'stack';
    return window.localStorage.getItem(LOGO_STORAGE_KEY) || 'stack';
}

function resolveNotebookIcon(nb) {
    const hasContent = Number(nb?.sourceCount || 0) > 0;
    if (!hasContent) return null;
    const emoji = String(nb?.emoji || '').trim();
    return emoji || null;
}

export default function HomePage() {
    const navigate = useNavigate();
    const { toggleTheme } = useTheme();
    const { showToast } = useToast();
    const [showSettings, setShowSettings] = useState(false);
    const [settingsInitialTab, setSettingsInitialTab] = useState('language');
    const [searchQuery, setSearchQuery] = useState('');
    const [workspaceResults, setWorkspaceResults] = useState([]);
    const [isSearchingWorkspace, setIsSearchingWorkspace] = useState(false);
    const [user, setUser] = useState(null);
    const [notebooks, setNotebooks] = useState([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isCreatingNotebook, setIsCreatingNotebook] = useState(false);
    const [notebookModalState, setNotebookModalState] = useState(null);
    const [error, setError] = useState('');
    const [showAccountMenu, setShowAccountMenu] = useState(false);
    const [logoOption, setLogoOption] = useState(getStoredLogoOption);
    const [activeTag, setActiveTag] = useState('');
    const [feeds, setFeeds] = useState([]);
    const [feedMeta, setFeedMeta] = useState({ total: 0, unread: 0 });
    const [feedError, setFeedError] = useState('');
    const [showFeedWorkspace, setShowFeedWorkspace] = useState(false);
    const logoOptions = getLogoOptions();
    const searchInputRef = useRef(null);
    const sessionUser = getStoredSession()?.user;
    const displayUser = user ? { ...user, avatar: user.avatar || sessionUser?.avatar || null } : sessionUser;

    const redirectToLogin = useCallback(() => {
        clearStoredSession();
        navigate('/login', { replace: true });
    }, [navigate]);

    useEffect(() => {
        if (typeof window !== 'undefined' && window.localStorage) {
            window.localStorage.setItem(LOGO_STORAGE_KEY, logoOption);
        }
    }, [logoOption]);

    useEffect(() => {
        let isMounted = true;

        const loadHomeData = async () => {
            try {
                setIsLoading(true);
                setError('');
                setFeedError('');
                const [currentUser, notebookItems, feedPayload] = await Promise.all([
                    appApi.auth.getCurrentUser(),
                    appApi.notebooks.list(),
                    appApi.feeds.list().catch((feedErr) => {
                        if (isMounted) {
                            setFeedError(feedErr.message || '加载订阅源失败');
                        }
                        return { items: [], meta: { total: 0, unread: 0 } };
                    }),
                ]);
                if (!isMounted) return;
                setUser(currentUser);
                setNotebooks(notebookItems);
                setFeeds(feedPayload.items || []);
                setFeedMeta(feedPayload.meta || { total: 0, unread: 0 });
            } catch (err) {
                if (!isMounted) return;
                if (isAuthError(err)) {
                    redirectToLogin();
                    return;
                }
                setError(err.message || '加载首页数据失败');
            } finally {
                if (isMounted) setIsLoading(false);
            }
        };

        loadHomeData();
        return () => {
            isMounted = false;
        };
    }, [redirectToLogin]);

    useEffect(() => {
        const handleShortcut = (event) => {
            const target = event.target instanceof HTMLElement ? event.target : null;
            if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) {
                return;
            }
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                searchInputRef.current?.focus();
                return;
            }
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
                event.preventDefault();
                openNotebookModal('create');
            }
        };
        document.addEventListener('keydown', handleShortcut);
        return () => document.removeEventListener('keydown', handleShortcut);
    }, []);

    useEffect(() => {
        const normalizedQuery = searchQuery.trim();
        if (!normalizedQuery) {
            setWorkspaceResults([]);
            return undefined;
        }

        let cancelled = false;
        const timer = window.setTimeout(async () => {
            try {
                setIsSearchingWorkspace(true);
                const items = await appApi.notebooks.searchWorkspace({ query: normalizedQuery });
                if (!cancelled) {
                    setWorkspaceResults(items);
                }
            } catch (err) {
                if (!cancelled && !isAuthError(err)) {
                    setError(err.message || '全局搜索失败');
                }
            } finally {
                if (!cancelled) {
                    setIsSearchingWorkspace(false);
                }
            }
        }, 220);

        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [searchQuery]);

    const availableTags = useMemo(() => {
        const tags = new Set();
        notebooks.forEach((notebook) => {
            (notebook.tags || []).forEach((tag) => {
                if (tag) {
                    tags.add(tag);
                }
            });
        });
        return Array.from(tags).sort((left, right) => left.localeCompare(right, 'zh-CN'));
    }, [notebooks]);

    const filteredNotebooks = useMemo(() => {
        const normalizedQuery = searchQuery.trim().toLowerCase();
        return notebooks.filter((nb) => {
            const matchesQuery = !normalizedQuery || nb.title.toLowerCase().includes(normalizedQuery)
                || (Array.isArray(nb.tags) && nb.tags.some((tag) => tag.toLowerCase().includes(normalizedQuery)));
            const matchesTag = !activeTag || (Array.isArray(nb.tags) && nb.tags.includes(activeTag));
            return matchesQuery && matchesTag;
        });
    }, [activeTag, notebooks, searchQuery]);

    const reloadFeeds = useCallback(async () => {
        try {
            const payload = await appApi.feeds.list();
            setFeeds(payload.items || []);
            setFeedMeta(payload.meta || { total: 0, unread: 0 });
            setFeedError('');
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setFeedError(err.message || '加载订阅源失败');
        }
    }, [redirectToLogin]);

    const { recentNotebooks, otherNotebooks } = useMemo(() => ({
        recentNotebooks: [...filteredNotebooks]
            .sort((left, right) => new Date(right.lastOpenedAt || 0).getTime() - new Date(left.lastOpenedAt || 0).getTime())
            .slice(0, RECENT_NOTEBOOK_LIMIT),
        otherNotebooks: [...filteredNotebooks]
            .sort((left, right) => new Date(right.lastOpenedAt || 0).getTime() - new Date(left.lastOpenedAt || 0).getTime())
            .slice(RECENT_NOTEBOOK_LIMIT),
    }), [filteredNotebooks]);
    const hasSearchQuery = searchQuery.trim().length > 0;

    const openNotebookModal = (mode, notebook) => {
        setNotebookModalState({
            mode,
            notebook: notebook || {
                title: '',
            },
        });
    };

    const handleCreateNotebook = async (payload) => {
        try {
            setIsCreatingNotebook(true);
            setError('');
            const notebook = await appApi.notebooks.create(payload);
            setNotebooks((prev) => [notebook, ...prev]);
            showToast({ type: 'success', title: '创建成功', message: `已创建《${notebook.title}》` });
            navigate(`/notebook/${notebook.id}`);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            const message = err.message || '创建笔记本失败';
            setError(message);
            showToast({ type: 'error', title: '创建失败', message });
            throw err;
        } finally {
            setIsCreatingNotebook(false);
        }
    };

    const handleUpdateNotebook = async (payload) => {
        try {
            setError('');
            const notebook = await appApi.notebooks.update(payload.id, {
                title: payload.title,
                tags: payload.tags,
            });
            setNotebooks((prev) => prev.map((item) => (item.id === notebook.id ? { ...item, ...notebook } : item)));
            showToast({ type: 'success', title: '已保存', message: `《${notebook.title}》已更新` });
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            const message = err.message || '更新笔记本失败';
            setError(message);
            showToast({ type: 'error', title: '更新失败', message });
            throw err;
        }
    };

    const handleDeleteNotebook = async (notebookId) => {
        try {
            setError('');
            await appApi.notebooks.remove(notebookId);
            setNotebooks((prev) => prev.filter((item) => item.id !== notebookId));
            showToast({ type: 'success', title: '已删除', message: '笔记本已移除' });
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            const message = err.message || '删除笔记本失败';
            setError(message);
            showToast({ type: 'error', title: '删除失败', message });
            throw err;
        }
    };

    const handleLogout = async () => {
        await appApi.auth.logout();
        showToast({ type: 'success', title: '已退出登录', message: '期待你下次回来继续整理研究' });
        redirectToLogin();
    };

    const renderNotebookGrid = (items, { includeCreateCard = true } = {}) => (
        <div className="home-grid">
            {includeCreateCard ? (
                <button
                    type="button"
                    className="home-card home-card-new animate-fade-in"
                    onClick={() => openNotebookModal('create')}
                >
                    <div className="home-card-new-inner">
                        <div className="home-card-new-icon"><span>+</span></div>
                        <span className="home-card-new-text">{isCreatingNotebook ? '创建中...' : '新建笔记本'}</span>
                    </div>
                </button>
            ) : null}

            {items.map((nb, index) => {
                const notebookIcon = resolveNotebookIcon(nb);
                return (
                <article
                    key={nb.id}
                    className="home-card animate-fade-in"
                    style={{ animationDelay: `${(index + 1) * 0.05}s` }}
                    onClick={() => navigate(`/notebook/${nb.id}`)}
                >
                    <div className="home-card-header">
                        <span className={`home-card-icon ${notebookIcon ? 'emoji' : 'default'}`}>
                            {notebookIcon || Hc.notebook}
                        </span>
                        <button
                            className="home-card-menu"
                            onClick={(event) => {
                                event.stopPropagation();
                                openNotebookModal('edit', nb);
                            }}
                        >
                            ⋮
                        </button>
                    </div>
                    <div className="home-card-body">
                        <h3 className="home-card-title">{nb.title}</h3>
                        <p className="home-card-meta">{nb.date} · {nb.sourceCount} 个来源</p>
                        {Array.isArray(nb.tags) && nb.tags.length > 0 ? (
                            <div className="home-card-tags">
                                {nb.tags.slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}
                            </div>
                        ) : null}
                    </div>
                </article>
                );
            })}
        </div>
    );

    const renderNotebookContent = () => {
        if (notebooks.length === 0) {
            return (
                <EmptyState
                    icon="✨"
                    title="还没有任何笔记本"
                    description="创建笔记本后开始导入来源。"
                    actionLabel="立即创建"
                    onAction={() => openNotebookModal('create')}
                />
            );
        }

        return (
            <>
                {availableTags.length > 0 ? (
                    <section className="home-tag-strip">
                        <button
                            type="button"
                            className={`home-tag-chip ${!activeTag ? 'active' : ''}`}
                            onClick={() => setActiveTag('')}
                        >
                            全部标签
                        </button>
                        {availableTags.map((tag) => (
                            <button
                                key={tag}
                                type="button"
                                className={`home-tag-chip ${activeTag === tag ? 'active' : ''}`}
                                onClick={() => setActiveTag((current) => (current === tag ? '' : tag))}
                            >
                                {tag}
                            </button>
                        ))}
                    </section>
                ) : null}

                {hasSearchQuery ? (
                    <section className="home-section">
                        <div className="home-section-heading">
                            <h2 className="home-section-title">全局搜索结果</h2>
                        </div>
                        {isSearchingWorkspace ? (
                            <div className="home-search-result-state"><Spinner inline label="搜索中..." /></div>
                        ) : workspaceResults.length > 0 ? (
                            <div className="home-search-results">
                                {workspaceResults.map((item) => (
                                    <button
                                        key={`${item.type}-${item.notebookId}-${item.articleId || 'root'}`}
                                        type="button"
                                        className="home-search-result-item"
                                        onClick={() => navigate(item.type === 'article' ? `/notebook/${item.notebookId}?articleId=${item.articleId}` : `/notebook/${item.notebookId}`)}
                                    >
                                        <span className="home-search-result-type">{item.type === 'article' ? '文章' : '笔记本'}</span>
                                        <span className="home-search-result-title">{item.title}</span>
                                        {Array.isArray(item.tags) && item.tags.length > 0 ? (
                                            <span className="home-search-result-tags">{item.tags.join(' · ')}</span>
                                        ) : null}
                                    </button>
                                ))}
                            </div>
                        ) : (
                            <EmptyState
                                icon="📚"
                                title="全局搜索暂未命中"
                                description="没有匹配结果，换个关键词试试。"
                                compact
                            />
                        )}
                    </section>
                ) : null}

                {hasSearchQuery ? (
                    filteredNotebooks.length > 0 ? (
                        <section className="home-section">
                            <div className="home-section-heading">
                                <h2 className="home-section-title">笔记本标题与标签命中</h2>
                            </div>
                            {renderNotebookGrid(filteredNotebooks, { includeCreateCard: false })}
                        </section>
                    ) : null
                ) : filteredNotebooks.length > 0 ? (
                    <>
                        <section className="home-section">
                            <div className="home-section-heading">
                                <h2 className="home-section-title">最近打开</h2>
                            </div>
                            {renderNotebookGrid(recentNotebooks, { includeCreateCard: true })}
                        </section>

                        {otherNotebooks.length > 0 ? (
                            <section className="home-section">
                                <div className="home-section-heading">
                                    <h2 className="home-section-title">全部笔记本</h2>
                                </div>
                                {renderNotebookGrid(otherNotebooks, { includeCreateCard: false })}
                            </section>
                        ) : null}
                    </>
                ) : (
                    <EmptyState
                        icon="🔎"
                        title="还没有笔记本"
                        description="先创建一个笔记本。"
                        actionLabel="立即创建"
                        onAction={() => openNotebookModal('create')}
                        compact
                    />
                )}
            </>
        );
    };

    return (
        <div className="home-page">
            <header className="home-topbar">
                <div className="home-topbar-left">
                    <button type="button" className="home-logo-switcher" onClick={() => setLogoOption((current) => {
                        const currentIndex = logoOptions.findIndex((item) => item.id === current);
                        const nextOption = logoOptions[(currentIndex + 1) % logoOptions.length];
                        return nextOption.id;
                    })}>
                        <AppLogo option={logoOption} text={String.fromCharCode(78, 111, 116, 101, 98, 111, 111, 107, 76, 77)} />
                    </button>
                </div>

                <div className="home-topbar-center">
                    <div className="home-search-wrapper">
                        <span className="home-search-icon">🔍</span>
                        <input
                            ref={searchInputRef}
                            className="input home-search-input"
                            placeholder="搜索笔记本、文章或标签..."
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                        />
                    </div>
                </div>

                <div className="home-topbar-right">
                    <button
                        className={`btn-icon home-feed-toggle-btn ${showFeedWorkspace ? 'active' : ''}`}
                        onClick={() => setShowFeedWorkspace(true)}
                        title="订阅源"
                    >
                        {Hc.feed}
                        {Number(feedMeta.unread || 0) > 0 ? (
                            <span className="home-feed-badge">{feedMeta.unread}</span>
                        ) : null}
                    </button>
                    <button className="btn-icon" onClick={toggleTheme} title="切换主题">
                        {Hc.theme}
                    </button>
                    <button
                        className="btn-icon"
                        onClick={() => {
                            setSettingsInitialTab('appearance');
                            setShowSettings(true);
                        }}
                        title="布局"
                    >
                        {Hc.layout}
                    </button>
                    <button
                        className="btn-icon"
                        onClick={() => {
                            setSettingsInitialTab('language');
                            setShowSettings(true);
                        }}
                        title="设置"
                    >
                        {Hc.settings}
                    </button>
                    <div className="home-avatar-wrapper">
                        <button type="button" className="home-avatar-btn" onClick={() => setShowAccountMenu((current) => !current)}>
                            <div className="home-avatar">
                                {displayUser?.avatar ? (
                                    <img className="home-avatar-image" src={displayUser.avatar} alt={displayUser.name || '用户头像'} />
                                ) : (
                                    displayUser?.name?.charAt(0) || 'U'
                                )}
                            </div>
                        </button>
                        <AccountMenu
                            open={showAccountMenu}
                            user={displayUser}
                            onClose={() => setShowAccountMenu(false)}
                            onOpenSettings={() => {
                                setShowAccountMenu(false);
                                setSettingsInitialTab('account');
                                setShowSettings(true);
                            }}
                            onLogout={handleLogout}
                        />
                    </div>
                </div>
            </header>

            <main className="home-main">
                <div className="home-content">
                    {error ? <ErrorBanner message={error} actionLabel="重新加载" onAction={() => window.location.reload()} /> : null}

                    {isLoading ? (
                        <div className="home-loading-state">
                            <Spinner size="lg" label="正在加载你的研究空间" />
                        </div>
                    ) : (
                        renderNotebookContent()
                    )}
                </div>
            </main>

            {showSettings ? <SettingsModal initialTab={settingsInitialTab} onClose={() => setShowSettings(false)} /> : null}
            {notebookModalState ? (
                <NotebookModal
                    mode={notebookModalState.mode}
                    notebook={notebookModalState.notebook}
                    onClose={() => setNotebookModalState(null)}
                    onSave={notebookModalState.mode === 'create' ? handleCreateNotebook : handleUpdateNotebook}
                    onDelete={notebookModalState.mode === 'edit' ? handleDeleteNotebook : undefined}
                    existingTitles={notebooks.map((item) => ({ id: item.id, title: item.title }))}
                    availableTags={availableTags}
                />
            ) : null}
            {showFeedWorkspace ? (
                <FeedWorkspaceModal
                    onClose={() => setShowFeedWorkspace(false)}
                    onFeedsChanged={() => void reloadFeeds()}
                    initialFeedData={{ feeds, meta: feedMeta, error: feedError }}
                />
            ) : null}
        </div>
    );
}
