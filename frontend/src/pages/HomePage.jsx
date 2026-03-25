import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AppLogo, { getLogoOptions } from '../components/common/AppLogo';
import AccountMenu from '../components/common/AccountMenu';
import EmptyState from '../components/common/EmptyState';
import ErrorBanner from '../components/common/ErrorBanner';
import Spinner from '../components/common/Spinner';
import { useToast } from '../components/common/ToastProvider';
import { useTheme } from '../contexts/useTheme';
import { appApi, clearStoredSession, isAuthError } from '../services/appApi';
import SettingsModal from '../components/SettingsModal';
import NotebookModal from '../components/NotebookModal';
import './HomePage.css';

const LOGO_STORAGE_KEY = '[REDACTED]-logo-option';
const RECENT_NOTEBOOK_LIMIT = 4;

function getStoredLogoOption() {
    if (typeof window === 'undefined' || !window.localStorage) return 'stack';
    return window.localStorage.getItem(LOGO_STORAGE_KEY) || 'stack';
}

export default function HomePage() {
    const navigate = useNavigate();
    const { theme, resolvedTheme, toggleTheme } = useTheme();
    const { showToast } = useToast();
    const [showSettings, setShowSettings] = useState(false);
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
    const logoOptions = getLogoOptions();

    const redirectToLogin = () => {
        clearStoredSession();
        navigate('/login', { replace: true });
    };

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
                const [currentUser, notebookItems] = await Promise.all([
                    appApi.auth.getCurrentUser(),
                    appApi.notebooks.list(),
                ]);
                if (!isMounted) return;
                setUser(currentUser);
                setNotebooks(notebookItems);
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

    const filteredNotebooks = useMemo(() => {
        const normalizedQuery = searchQuery.trim().toLowerCase();
        if (!normalizedQuery) return notebooks;
        return notebooks.filter((nb) => (
            nb.title.toLowerCase().includes(normalizedQuery)
            || (Array.isArray(nb.tags) && nb.tags.some((tag) => tag.toLowerCase().includes(normalizedQuery)))
        ));
    }, [notebooks, searchQuery]);

    const { recentNotebooks, otherNotebooks } = useMemo(() => ({
        recentNotebooks: filteredNotebooks.slice(0, RECENT_NOTEBOOK_LIMIT),
        otherNotebooks: filteredNotebooks.slice(RECENT_NOTEBOOK_LIMIT),
    }), [filteredNotebooks]);

    const openNotebookModal = (mode, notebook) => {
        setNotebookModalState({
            mode,
            notebook: notebook || {
                title: '',
                emoji: '📒',
                color: '#8B7355',
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
                emoji: payload.emoji,
                color: payload.color,
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

    const renderNotebookGrid = (items) => (
        <div className="home-grid">
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

            {items.map((nb, index) => (
                <article
                    key={nb.id}
                    className="home-card animate-fade-in"
                    style={{ animationDelay: `${(index + 1) * 0.05}s` }}
                    onClick={() => navigate(`/notebook/${nb.id}`)}
                >
                    <div className="home-card-header" style={{ background: nb.color }}>
                        <span className="home-card-emoji">{nb.emoji}</span>
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
            ))}
        </div>
    );

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
                            className="input home-search-input"
                            placeholder="搜索笔记本标题或标签..."
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                        />
                    </div>
                </div>

                <div className="home-topbar-right">
                    <button className="btn-icon" onClick={toggleTheme} title="切换主题">
                        {(theme === 'dark' || resolvedTheme === 'dark') ? '☀️' : '🌙'}
                    </button>
                    <button className="btn-icon" onClick={() => setShowSettings(true)} title="设置">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
                            <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.64-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.57 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
                        </svg>
                    </button>
                    <div className="home-avatar-wrapper">
                        <button type="button" className="home-avatar-btn" onClick={() => setShowAccountMenu((current) => !current)}>
                            <div className="home-avatar">{user?.name?.charAt(0) || 'U'}</div>
                        </button>
                        <AccountMenu
                            open={showAccountMenu}
                            user={user}
                            onClose={() => setShowAccountMenu(false)}
                            onOpenSettings={() => {
                                setShowAccountMenu(false);
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
                    ) : notebooks.length === 0 ? (
                        <EmptyState
                            icon="✨"
                            title="还没有任何笔记本"
                            description="先创建一个研究空间，再导入网页、PDF 或笔记内容。后续首页会自动为你展示最近打开与分类筛选。"
                            actionLabel="立即创建"
                            onAction={() => openNotebookModal('create')}
                        />
                    ) : filteredNotebooks.length === 0 ? (
                        <EmptyState
                            icon="🔎"
                            title="没有找到匹配结果"
                            description="可以试试搜索标题关键词、标签，或者切换 logo 后重新整理你的首页视图。"
                            actionLabel="清空搜索"
                            onAction={() => setSearchQuery('')}
                            compact
                        />
                    ) : (
                        <>
                            <section className="home-section">
                                <div className="home-section-heading">
                                    <h2 className="home-section-title">最近打开</h2>
                                    <span className="home-section-caption">优先展示你最近回看的研究空间</span>
                                </div>
                                {renderNotebookGrid(recentNotebooks)}
                            </section>

                            {searchQuery.trim() ? (
                                <section className="home-section">
                                    <div className="home-section-heading">
                                        <h2 className="home-section-title">全局搜索结果</h2>
                                        <span className="home-section-caption">匹配笔记本标题、标签，以及文章标题与正文</span>
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
                                            description="当前没有匹配到笔记本或文章内容，你可以继续输入更具体的关键词。"
                                            compact
                                        />
                                    )}
                                </section>
                            ) : null}

                            {otherNotebooks.length > 0 ? (
                                <section className="home-section">
                                    <div className="home-section-heading">
                                        <h2 className="home-section-title">全部笔记本</h2>
                                        <span className="home-section-caption">按更新时间与搜索条件自动筛选</span>
                                    </div>
                                    {renderNotebookGrid(otherNotebooks)}
                                </section>
                            ) : null}
                        </>
                    )}
                </div>
            </main>

            {showSettings ? <SettingsModal onClose={() => setShowSettings(false)} /> : null}
            {notebookModalState ? (
                <NotebookModal
                    mode={notebookModalState.mode}
                    notebook={notebookModalState.notebook}
                    onClose={() => setNotebookModalState(null)}
                    onSave={notebookModalState.mode === 'create' ? handleCreateNotebook : handleUpdateNotebook}
                    onDelete={notebookModalState.mode === 'edit' ? handleDeleteNotebook : undefined}
                    existingTitles={notebooks.map((item) => ({ id: item.id, title: item.title }))}
                />
            ) : null}
        </div>
    );
}
