import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { useToast } from './common/useToast';
import AddFeedModal from './AddFeedModal';
import ImportToNotebookModal from './ImportToNotebookModal';
import './FeedWorkspaceModal.css';

const ENTRY_PAGE_SIZE = 100;
const DEFAULT_VISIBLE_ENTRY_COUNT = 3;
const COLLAPSED_CONTENT_CHARS = 240;

function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(date);
}

function getFeedIconSrc(feed) {
    const rawIcon = String(feed?.iconData || '').trim();
    if (rawIcon) {
        return rawIcon.startsWith('data:') ? rawIcon : `data:image/png;base64,${rawIcon}`;
    }
    const source = String(feed?.siteUrl || feed?.feedUrl || '').trim();
    if (!source) return '';
    try {
        const hostname = new URL(source).hostname;
        if (!hostname) return '';
        return `https://www.google.com/s2/favicons?domain=${hostname}&sz=64`;
    } catch {
        return '';
    }
}

function getFeedInitial(feed) {
    const title = String(feed?.title || '').trim();
    if (!title) return 'R';
    return title.charAt(0).toUpperCase();
}

function matchesEntry(entry, keyword) {
    if (!keyword) return true;
    const haystack = [
        entry?.title,
        entry?.aiSummary,
        entry?.contentPreview,
        entry?.author,
        entry?.feedTitle,
    ]
        .map((item) => String(item || '').toLowerCase())
        .join(' ');
    return haystack.includes(keyword);
}

function stripHtml(value) {
    if (!value) return '';
    const container = document.createElement('div');
    container.innerHTML = String(value);
    return (container.textContent || container.innerText || '').replace(/\s+/g, ' ').trim();
}

function truncateText(value, maxChars = COLLAPSED_CONTENT_CHARS) {
    if (!value) return '';
    const normalized = String(value).trim();
    if (normalized.length <= maxChars) return normalized;
    return `${normalized.slice(0, maxChars).trimEnd()}...`;
}

export default function FeedWorkspaceModal({
    onClose,
    onFeedsChanged,
    initialFeedData = { feeds: [], meta: { total: 0, unread: 0 }, error: '' },
}) {
    const { showToast } = useToast();
    const [feeds, setFeeds] = useState(initialFeedData.feeds || []);
    const [feedMeta, setFeedMeta] = useState(initialFeedData.meta || { total: 0, unread: 0 });
    const [feedError, setFeedError] = useState(initialFeedData.error || '');
    const [categories, setCategories] = useState([]);
    const [notebooks, setNotebooks] = useState([]);
    const [targetNotebookId, setTargetNotebookId] = useState('');
    const [selectedFeedId, setSelectedFeedId] = useState('');
    const [selectedCategory, setSelectedCategory] = useState('');
    const [showUnreadOnly, setShowUnreadOnly] = useState(true);
    const [feedSearch, setFeedSearch] = useState('');
    const [entrySearch, setEntrySearch] = useState('');
    const [entries, setEntries] = useState([]);
    const [entriesMeta, setEntriesMeta] = useState({ total: 0, unread: 0 });
    const [selectedEntryId, setSelectedEntryId] = useState(null);
    const [selectedEntryIds, setSelectedEntryIds] = useState([]);
    const [showAllEntries, setShowAllEntries] = useState(false);
    const [expandedEntryIds, setExpandedEntryIds] = useState([]);
    const [summaryEntryIds, setSummaryEntryIds] = useState([]);
    const [entryContentMap, setEntryContentMap] = useState({});
    const [loadingContentEntryIds, setLoadingContentEntryIds] = useState([]);
    const [isLoadingFeeds, setIsLoadingFeeds] = useState(false);
    const [isLoadingEntries, setIsLoadingEntries] = useState(false);
    const [isLoadingMoreEntries, setIsLoadingMoreEntries] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [isMarkingRead, setIsMarkingRead] = useState(false);
    const [isRefreshingFeed, setIsRefreshingFeed] = useState(false);
    const [feedback, setFeedback] = useState('');
    const [showAddFeedModal, setShowAddFeedModal] = useState(false);
    const [showImportModal, setShowImportModal] = useState(false);
    const feedSearchInputRef = useRef(null);
    const entrySearchInputRef = useRef(null);

    useEscapeToClose(
        onClose,
        !showAddFeedModal
        && !showImportModal
        && !isImporting
        && !isMarkingRead
        && !isLoadingFeeds
        && !isLoadingEntries
        && !isRefreshingFeed,
    );

    const loadFeedsAndMeta = useCallback(async () => {
        try {
            setIsLoadingFeeds(true);
            const payload = await appApi.feeds.list();
            setFeeds(payload.items || []);
            setFeedMeta(payload.meta || { total: 0, unread: 0 });
            setFeedError('');
        } catch (err) {
            setFeedError(err.message || '加载订阅源失败');
        } finally {
            setIsLoadingFeeds(false);
        }
    }, []);

    useEffect(() => {
        let cancelled = false;
        const loadBaseData = async () => {
            try {
                const [categoryItems, notebookItems] = await Promise.all([
                    appApi.feeds.listCategories(),
                    appApi.notebooks.list(),
                ]);
                if (cancelled) return;
                setCategories(categoryItems || []);
                setNotebooks(notebookItems || []);
                setTargetNotebookId(notebookItems?.[0]?.id || '');
            } catch {
                if (cancelled) return;
                setCategories([]);
            }
        };
        void loadBaseData();
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        void loadFeedsAndMeta();
    }, [loadFeedsAndMeta]);

    const availableCategories = useMemo(() => {
        const map = new Map();
        for (const item of categories) {
            const title = String(item?.title || '').trim();
            if (title) map.set(title, title);
        }
        for (const feed of feeds) {
            const title = String(feed?.categoryName || '').trim();
            if (title) map.set(title, title);
        }
        return Array.from(map.values()).sort((a, b) => a.localeCompare(b, 'zh-CN'));
    }, [categories, feeds]);

    const filteredFeeds = useMemo(() => {
        const keyword = feedSearch.trim().toLowerCase();
        return feeds.filter((feed) => {
            if (selectedCategory && String(feed.categoryName || '').trim() !== selectedCategory) {
                return false;
            }
            if (showUnreadOnly && Number(feed.unreadCount || 0) <= 0) {
                return false;
            }
            if (!keyword) return true;
            return String(feed.title || '').toLowerCase().includes(keyword)
                || String(feed.categoryName || '').toLowerCase().includes(keyword)
                || String(feed.feedUrl || '').toLowerCase().includes(keyword);
        });
    }, [feedSearch, feeds, selectedCategory, showUnreadOnly]);

    useEffect(() => {
        if (filteredFeeds.length === 0) {
            setSelectedFeedId('');
            return;
        }
        const exists = filteredFeeds.some((item) => item.id === selectedFeedId);
        if (!exists) {
            setSelectedFeedId(filteredFeeds[0].id);
        }
    }, [filteredFeeds, selectedFeedId]);

    const selectedFeed = useMemo(
        () => filteredFeeds.find((item) => item.id === selectedFeedId) || null,
        [filteredFeeds, selectedFeedId],
    );

    const loadEntries = useCallback(async ({ append = false } = {}) => {
        if (!selectedFeedId) {
            setEntries([]);
            setEntriesMeta({ total: 0, unread: 0 });
            setSelectedEntryId(null);
            return;
        }
        try {
            if (append) {
                setIsLoadingMoreEntries(true);
            } else {
                setIsLoadingEntries(true);
                setFeedback('');
            }
            const offset = append ? entries.length : 0;
            const payload = await appApi.feeds.listEntries({
                feedId: selectedFeedId,
                status: showUnreadOnly ? 'unread' : 'all',
                limit: ENTRY_PAGE_SIZE,
                offset,
            });
            const nextItems = payload.items || [];
            setEntries((prev) => (append ? [...prev, ...nextItems] : nextItems));
            setEntriesMeta(payload.meta || { total: 0, unread: 0 });
            if (!append) {
                setSelectedEntryIds([]);
                setSelectedEntryId(nextItems[0]?.entryId || null);
            }
        } catch (err) {
            setFeedback(err.message || '加载订阅文章失败');
        } finally {
            setIsLoadingEntries(false);
            setIsLoadingMoreEntries(false);
        }
    }, [entries.length, selectedFeedId, showUnreadOnly]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            void loadEntries({ append: false });
        }, 220);
        return () => window.clearTimeout(timer);
    }, [loadEntries]);

    const normalizedEntrySearch = entrySearch.trim().toLowerCase();
    const filteredEntries = useMemo(
        () => entries.filter((entry) => matchesEntry(entry, normalizedEntrySearch)),
        [entries, normalizedEntrySearch],
    );
    const visibleEntries = useMemo(
        () => (showAllEntries ? filteredEntries : filteredEntries.slice(0, DEFAULT_VISIBLE_ENTRY_COUNT)),
        [filteredEntries, showAllEntries],
    );

    useEffect(() => {
        if (filteredEntries.length === 0) {
            setSelectedEntryId(null);
            return;
        }
        if (!filteredEntries.some((item) => item.entryId === selectedEntryId)) {
            setSelectedEntryId(filteredEntries[0].entryId);
        }
    }, [filteredEntries, selectedEntryId]);

    useEffect(() => {
        setSelectedEntryIds((previous) => previous.filter((entryId) => entries.some((entry) => entry.entryId === entryId)));
    }, [entries]);

    useEffect(() => {
        const idSet = new Set(entries.map((item) => item.entryId));
        setExpandedEntryIds((previous) => previous.filter((entryId) => idSet.has(entryId)));
        setSummaryEntryIds((previous) => previous.filter((entryId) => idSet.has(entryId)));
        setEntryContentMap((previous) => {
            const next = {};
            Object.entries(previous).forEach(([entryId, content]) => {
                if (idSet.has(Number(entryId))) {
                    next[entryId] = content;
                }
            });
            return next;
        });
    }, [entries]);

    useEffect(() => {
        setShowAllEntries(false);
    }, [selectedFeedId, showUnreadOnly, entrySearch]);

    const visibleEntryIds = useMemo(() => visibleEntries.map((item) => item.entryId), [visibleEntries]);
    const selectedCount = selectedEntryIds.length;
    const allCurrentChecked = visibleEntryIds.length > 0 && visibleEntryIds.every((entryId) => selectedEntryIds.includes(entryId));
    const hasMoreEntries = entries.length < Number(entriesMeta.total || 0);
    const hasHiddenVisibleEntries = filteredEntries.length > DEFAULT_VISIBLE_ENTRY_COUNT && !showAllEntries;
    const noEntryMessage = normalizedEntrySearch ? '没有匹配的文章' : '暂无文章';
    const currentEntryIndex = filteredEntries.findIndex((item) => item.entryId === selectedEntryId);
    const hasPrevEntry = currentEntryIndex > 0;
    const hasNextEntry = currentEntryIndex >= 0 && currentEntryIndex < filteredEntries.length - 1;

    const toggleSelectEntry = (entryId) => {
        setSelectedEntryIds((prev) => (
            prev.includes(entryId)
                ? prev.filter((id) => id !== entryId)
                : [...prev, entryId]
        ));
    };

    const loadEntryContent = useCallback(async (entryId) => {
        if (entryContentMap[entryId] || loadingContentEntryIds.includes(entryId)) return;
        try {
            setLoadingContentEntryIds((previous) => [...previous, entryId]);
            const detail = await appApi.feeds.getEntry(entryId);
            const fullText = stripHtml(detail?.contentHtml || detail?.contentPreview || '');
            if (fullText) {
                setEntryContentMap((previous) => ({ ...previous, [entryId]: fullText }));
            }
        } catch (err) {
            setFeedback(err.message || '加载全文失败');
        } finally {
            setLoadingContentEntryIds((previous) => previous.filter((id) => id !== entryId));
        }
    }, [entryContentMap, loadingContentEntryIds]);

    const handleToggleEntryExpand = useCallback(async (entry, event) => {
        event.stopPropagation();
        const entryId = entry.entryId;
        const isExpanded = expandedEntryIds.includes(entryId);
        if (isExpanded) {
            setExpandedEntryIds((previous) => previous.filter((id) => id !== entryId));
            return;
        }
        setExpandedEntryIds((previous) => [...previous, entryId]);
        await loadEntryContent(entryId);
    }, [expandedEntryIds, loadEntryContent]);

    const handleToggleEntrySummary = useCallback((entryId, event) => {
        event.stopPropagation();
        setSummaryEntryIds((previous) => (
            previous.includes(entryId)
                ? previous.filter((id) => id !== entryId)
                : [...previous, entryId]
        ));
    }, []);

    const handleJumpEntry = useCallback((direction) => {
        if (filteredEntries.length === 0) return;
        const currentIndex = currentEntryIndex >= 0 ? currentEntryIndex : 0;
        const targetIndex = direction === 'prev'
            ? Math.max(0, currentIndex - 1)
            : Math.min(filteredEntries.length - 1, currentIndex + 1);
        const target = filteredEntries[targetIndex];
        if (!target) return;
        if (!showAllEntries && targetIndex >= DEFAULT_VISIBLE_ENTRY_COUNT) {
            setShowAllEntries(true);
        }
        setSelectedEntryId(target.entryId);
    }, [currentEntryIndex, filteredEntries, showAllEntries]);

    const handleToggleAllEntries = useCallback(() => {
        if (allCurrentChecked) {
            setSelectedEntryIds((previous) => previous.filter((entryId) => !visibleEntryIds.includes(entryId)));
            return;
        }
        setSelectedEntryIds((previous) => Array.from(new Set([...previous, ...visibleEntryIds])));
    }, [allCurrentChecked, visibleEntryIds]);

    const handleOpenImportModal = useCallback(() => {
        if (selectedEntryIds.length === 0) {
            setFeedback('请先选择要导入的文章');
            return;
        }
        if (notebooks.length === 0) {
            setFeedback('请先创建至少一个笔记本');
            return;
        }
        setShowImportModal(true);
    }, [notebooks.length, selectedEntryIds.length]);

    const handleBatchImport = async (notebookId = targetNotebookId) => {
        if (!notebookId || selectedEntryIds.length === 0) {
            setFeedback('请选择目标笔记本并勾选至少一篇文章');
            return;
        }
        try {
            setIsImporting(true);
            const payload = await appApi.feeds.importToNotebook({
                notebookId,
                entryIds: selectedEntryIds,
            });
            setFeedback(`已导入 ${payload?.meta?.importedCount || selectedEntryIds.length} 篇文章`);
            setTargetNotebookId(notebookId);
            setShowImportModal(false);
            showToast({
                type: 'success',
                title: '导入成功',
                message: `已导入 ${payload?.meta?.importedCount || selectedEntryIds.length} 篇文章`,
            });
            await Promise.all([
                loadFeedsAndMeta(),
                loadEntries({ append: false }),
            ]);
            onFeedsChanged?.();
        } catch (err) {
            const message = err.message || '批量导入失败';
            setFeedback(message);
            showToast({ type: 'error', title: '导入失败', message });
        } finally {
            setIsImporting(false);
        }
    };

    const handleMarkSelectedRead = useCallback(async () => {
        if (selectedEntryIds.length === 0) {
            setFeedback('请先选择文章');
            return;
        }
        try {
            setIsMarkingRead(true);
            await appApi.feeds.updateEntriesStatus({ entryIds: selectedEntryIds, status: 'read' });
            setFeedback(`已标记 ${selectedEntryIds.length} 篇为已读`);
            setSelectedEntryIds([]);
            await Promise.all([
                loadFeedsAndMeta(),
                loadEntries({ append: false }),
            ]);
            onFeedsChanged?.();
            showToast({ type: 'success', title: '操作成功', message: '已标记为已读' });
        } catch (err) {
            const message = err.message || '标记已读失败';
            setFeedback(message);
            showToast({ type: 'error', title: '操作失败', message });
        } finally {
            setIsMarkingRead(false);
        }
    }, [selectedEntryIds, loadEntries, loadFeedsAndMeta, onFeedsChanged, showToast]);

    const handleRefreshFeed = async (feedId) => {
        try {
            setIsRefreshingFeed(true);
            await appApi.feeds.refresh(feedId);
            await Promise.all([
                loadFeedsAndMeta(),
                loadEntries({ append: false }),
            ]);
            onFeedsChanged?.();
            showToast({ type: 'success', title: '已刷新', message: '订阅源刷新成功' });
        } catch (err) {
            const message = err.message || '刷新订阅源失败';
            setFeedback(message);
            showToast({ type: 'error', title: '刷新失败', message });
        } finally {
            setIsRefreshingFeed(false);
        }
    };

    const handleRemoveFeed = async (feed) => {
        const confirmed = window.confirm(`确定取消订阅《${feed.title}》吗？`);
        if (!confirmed) return;
        try {
            await appApi.feeds.remove(feed.id);
            await loadFeedsAndMeta();
            onFeedsChanged?.();
            showToast({ type: 'success', title: '已取消订阅', message: feed.title });
        } catch (err) {
            const message = err.message || '取消订阅失败';
            setFeedback(message);
            showToast({ type: 'error', title: '操作失败', message });
        }
    };

    const handleFeedCreated = async (item) => {
        setShowAddFeedModal(false);
        await loadFeedsAndMeta();
        if (item?.id) {
            setSelectedFeedId(item.id);
        }
        onFeedsChanged?.();
    };

    useEffect(() => {
        const handleShortcut = (event) => {
            if (showAddFeedModal || showImportModal) return;
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const target = event.target instanceof HTMLElement ? event.target : null;
            if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) {
                return;
            }
            const key = event.key.toLowerCase();
            if (key === '/') {
                event.preventDefault();
                entrySearchInputRef.current?.focus();
                return;
            }
            if (key === 'f') {
                event.preventDefault();
                feedSearchInputRef.current?.focus();
                return;
            }
            if (key === 'a') {
                event.preventDefault();
                handleToggleAllEntries();
                return;
            }
            if (key === 'i') {
                event.preventDefault();
                handleOpenImportModal();
                return;
            }
            if (key === 'm') {
                event.preventDefault();
                void handleMarkSelectedRead();
            }
        };
        document.addEventListener('keydown', handleShortcut);
        return () => document.removeEventListener('keydown', handleShortcut);
    }, [
        showAddFeedModal,
        showImportModal,
        handleToggleAllEntries,
        handleOpenImportModal,
        handleMarkSelectedRead,
    ]);

    return (
        <div className="feed-workspace-overlay" onClick={onClose}>
            <div className="feed-workspace-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <header className="feed-workspace-header">
                    <div>
                        <h3>订阅源</h3>
                        <p>{Number(feedMeta.total || feeds.length)} 个订阅源 · {Number(feedMeta.unread || 0)} 篇未读</p>
                    </div>
                    <button type="button" className="feed-workspace-close" onClick={onClose}>✕</button>
                </header>

                <div className="feed-workspace-body">
                    <aside className="feed-workspace-sidebar">
                        <div className="feed-workspace-sidebar-top">
                            <button
                                type="button"
                                className="feed-workspace-add-btn"
                                onClick={() => setShowAddFeedModal(true)}
                            >
                                + 添加订阅源
                            </button>
                            <button
                                type="button"
                                className={`feed-workspace-toggle-btn ${showUnreadOnly ? 'active' : ''}`}
                                onClick={() => setShowUnreadOnly((value) => !value)}
                            >
                                {showUnreadOnly ? '仅看未读' : '显示全部'}
                            </button>
                        </div>

                        <input
                            ref={feedSearchInputRef}
                            className="feed-workspace-search"
                            placeholder="筛选订阅源"
                            value={feedSearch}
                            onChange={(event) => setFeedSearch(event.target.value)}
                        />

                        <div className="feed-workspace-category-chips">
                            <button
                                type="button"
                                className={`feed-workspace-category-chip ${!selectedCategory ? 'active' : ''}`}
                                onClick={() => setSelectedCategory('')}
                            >
                                全部分类
                            </button>
                            {availableCategories.map((category) => (
                                <button
                                    key={category}
                                    type="button"
                                    className={`feed-workspace-category-chip ${selectedCategory === category ? 'active' : ''}`}
                                    onClick={() => setSelectedCategory((current) => (current === category ? '' : category))}
                                >
                                    {category}
                                </button>
                            ))}
                        </div>

                        <div className="feed-workspace-feed-list">
                            {isLoadingFeeds ? <p className="feed-workspace-empty">加载订阅源中...</p> : null}
                            {!isLoadingFeeds && filteredFeeds.length === 0 ? <p className="feed-workspace-empty">暂无符合条件的订阅源</p> : null}
                            {filteredFeeds.map((feed) => {
                                const feedIconSrc = getFeedIconSrc(feed);
                                return (
                                    <article
                                        key={feed.id}
                                        role="button"
                                        tabIndex={0}
                                        className={`feed-workspace-feed-item ${selectedFeedId === feed.id ? 'active' : ''}`}
                                        onClick={() => setSelectedFeedId(feed.id)}
                                        onKeyDown={(event) => {
                                            if (event.key === 'Enter' || event.key === ' ') {
                                                event.preventDefault();
                                                setSelectedFeedId(feed.id);
                                            }
                                        }}
                                    >
                                        <div className="feed-workspace-feed-item-head">
                                            <div className="feed-workspace-feed-item-title">
                                                <div className="feed-workspace-feed-item-icon">
                                                    <span>{getFeedInitial(feed)}</span>
                                                    {feedIconSrc ? (
                                                        <img
                                                            src={feedIconSrc}
                                                            alt=""
                                                            loading="lazy"
                                                            onError={(event) => {
                                                                event.currentTarget.style.display = 'none';
                                                            }}
                                                        />
                                                    ) : null}
                                                </div>
                                                <strong>{feed.title}</strong>
                                            </div>
                                            <span>{Number(feed.unreadCount || 0)}</span>
                                        </div>
                                        <p>{feed.categoryName || '未分类'} · {feed.feedUrl || '—'}</p>
                                        <div className="feed-workspace-feed-item-actions" onClick={(event) => event.stopPropagation()}>
                                            <button type="button" onClick={() => void handleRefreshFeed(feed.id)}>刷新</button>
                                            <button type="button" className="danger" onClick={() => void handleRemoveFeed(feed)}>取消订阅</button>
                                        </div>
                                    </article>
                                );
                            })}
                        </div>
                    </aside>

                    <section className="feed-workspace-main">
                        <div className="feed-workspace-main-toolbar">
                            <div className="feed-workspace-search-wrap">
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path fill="currentColor" d="M10 4a6 6 0 1 0 3.874 10.582l4.272 4.272 1.414-1.414-4.272-4.272A6 6 0 0 0 10 4Zm0 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z" />
                                </svg>
                                <input
                                    ref={entrySearchInputRef}
                                    className="feed-workspace-search"
                                    placeholder="搜索文章"
                                    value={entrySearch}
                                    onChange={(event) => setEntrySearch(event.target.value)}
                                />
                            </div>
                            <div className="feed-workspace-toolbar-actions">
                                <button
                                    type="button"
                                    className="feed-workspace-icon-btn primary"
                                    onClick={handleOpenImportModal}
                                    disabled={isImporting || selectedCount === 0 || notebooks.length === 0}
                                    title="导入到笔记本"
                                    aria-label="导入到笔记本"
                                >
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path fill="currentColor" d="M5 4h14a2 2 0 0 1 2 2v10h-2V6H5v12h6v2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm7 5 5 5h-3v6h-4v-6H7l5-5Z" />
                                    </svg>
                                    <span className="feed-workspace-icon-badge">{selectedCount}</span>
                                </button>
                                <button
                                    type="button"
                                    className="feed-workspace-icon-btn"
                                    onClick={handleToggleAllEntries}
                                    title={allCurrentChecked ? '取消全选' : '全选当前页'}
                                    aria-label={allCurrentChecked ? '取消全选' : '全选当前页'}
                                >
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path fill="currentColor" d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm1 2v12h12V6H6Zm2 5h8v2H8v-2Z" />
                                    </svg>
                                </button>
                                <button
                                    type="button"
                                    className="feed-workspace-icon-btn"
                                    onClick={() => setSelectedEntryIds([])}
                                    title="清空选择"
                                    aria-label="清空选择"
                                >
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path fill="currentColor" d="M8.586 7.172 12 10.586l3.414-3.414 1.414 1.414L13.414 12l3.414 3.414-1.414 1.414L12 13.414l-3.414 3.414-1.414-1.414L10.586 12 7.172 8.586l1.414-1.414ZM5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" />
                                    </svg>
                                </button>
                                <button
                                    type="button"
                                    className="feed-workspace-icon-btn"
                                    onClick={() => void handleMarkSelectedRead()}
                                    disabled={selectedCount === 0 || isMarkingRead}
                                    title="标记已读"
                                    aria-label="标记已读"
                                >
                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                        <path fill="currentColor" d="m9.55 16.6-4.24-4.24 1.42-1.41 2.82 2.82 7.07-7.07 1.41 1.41-8.48 8.49Z" />
                                    </svg>
                                </button>
                            </div>
                        </div>

                        <div className="feed-workspace-selection-bar">
                            <span>
                                {selectedFeed?.title || '未选择订阅源'} · 共 {entriesMeta.total || entries.length} 篇
                                {notebooks.length === 0 ? ' · 暂无笔记本' : ''}
                            </span>
                            <span>{selectedCount > 0 ? `已选择 ${selectedCount} 篇` : '未选择文章'}</span>
                        </div>

                        <div className="feed-workspace-entry-list">
                            {isLoadingEntries ? <p className="feed-workspace-empty">加载文章中...</p> : null}
                            {!isLoadingEntries && filteredEntries.length === 0 ? <p className="feed-workspace-empty">{noEntryMessage}</p> : null}
                            {visibleEntries.map((entry) => {
                                const entryId = entry.entryId;
                                const isExpanded = expandedEntryIds.includes(entryId);
                                const isSummaryOpen = summaryEntryIds.includes(entryId);
                                const isLoadingContent = loadingContentEntryIds.includes(entryId);
                                const fullContent = entryContentMap[entryId];
                                const fallbackContent = stripHtml(entry.contentPreview || '');
                                const contentText = fullContent || fallbackContent;
                                const contentToRender = isExpanded ? contentText : truncateText(contentText);
                                return (
                                    <article
                                        key={entryId}
                                        className={`feed-workspace-entry-card ${selectedEntryId === entryId ? 'active' : ''}`}
                                        onClick={() => setSelectedEntryId(entryId)}
                                    >
                                        <div className="feed-workspace-entry-card-head">
                                            <input
                                                type="checkbox"
                                                checked={selectedEntryIds.includes(entryId)}
                                                onClick={(event) => event.stopPropagation()}
                                                onChange={() => toggleSelectEntry(entryId)}
                                            />
                                            <div className="feed-workspace-entry-card-title-wrap">
                                                <strong>{entry.title}</strong>
                                                <p>
                                                    {entry.feedTitle || selectedFeed?.title || '订阅源'}
                                                    {entry.author ? ` · ${entry.author}` : ''}
                                                    {' · '}
                                                    {formatTime(entry.publishedAt)}
                                                </p>
                                            </div>
                                            <div className="feed-workspace-entry-card-actions">
                                                <button
                                                    type="button"
                                                    className={`feed-workspace-entry-icon-btn ${isSummaryOpen ? 'active' : ''}`}
                                                    onClick={(event) => handleToggleEntrySummary(entryId, event)}
                                                    title="AI 摘要"
                                                    aria-label="AI 摘要"
                                                >
                                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                                        <path fill="currentColor" d="m11.13 2 1.71 4.36L17.2 8.1l-4.36 1.71L11.13 14l-1.72-4.2L5.2 8.1l4.21-1.74L11.13 2ZM18 13l1.04 2.64L21.7 16.7l-2.66 1.04L18 20.4l-1.04-2.66L14.3 16.7l2.66-1.06L18 13ZM6 13l1.04 2.64L9.7 16.7l-2.66 1.04L6 20.4l-1.04-2.66L2.3 16.7l2.66-1.06L6 13Z" />
                                                    </svg>
                                                </button>
                                                <button
                                                    type="button"
                                                    className="feed-workspace-entry-icon-btn"
                                                    onClick={(event) => {
                                                        event.stopPropagation();
                                                        if (!entry.url) return;
                                                        window.open(entry.url, '_blank', 'noopener,noreferrer');
                                                    }}
                                                    disabled={!entry.url}
                                                    title="打开原文"
                                                    aria-label="打开原文"
                                                >
                                                    <svg viewBox="0 0 24 24" aria-hidden="true">
                                                        <path fill="currentColor" d="M14 3h7v7h-2V6.41l-9.3 9.3-1.4-1.42 9.29-9.29H14V3ZM5 5h6v2H7v10h10v-4h2v6H5V5Z" />
                                                    </svg>
                                                </button>
                                            </div>
                                        </div>

                                        {isSummaryOpen ? (
                                            <div className="feed-workspace-ai-summary">
                                                <div className="feed-workspace-ai-summary-head">
                                                    <span className="feed-workspace-ai-summary-icon">✦</span>
                                                    <strong>AI 摘要</strong>
                                                </div>
                                                <p>{entry.aiSummary || '暂无摘要'}</p>
                                            </div>
                                        ) : null}

                                        <div className={`feed-workspace-entry-content ${isExpanded ? 'expanded' : ''}`}>
                                            {contentToRender || entry.aiSummary || '暂无内容'}
                                        </div>

                                        <div className="feed-workspace-entry-bottom">
                                            <button
                                                type="button"
                                                className="feed-workspace-expand-btn"
                                                disabled={isLoadingContent}
                                                onClick={(event) => {
                                                    void handleToggleEntryExpand(entry, event);
                                                }}
                                            >
                                                {isLoadingContent ? '加载全文中...' : isExpanded ? '收起卡片' : '展开卡片'}
                                            </button>
                                        </div>
                                    </article>
                                );
                            })}
                            {hasHiddenVisibleEntries ? (
                                <button
                                    type="button"
                                    className="feed-workspace-load-more"
                                    onClick={() => setShowAllEntries(true)}
                                >
                                    查看更多（{filteredEntries.length - DEFAULT_VISIBLE_ENTRY_COUNT} 条）
                                </button>
                            ) : null}
                            {showAllEntries && filteredEntries.length > DEFAULT_VISIBLE_ENTRY_COUNT ? (
                                <button
                                    type="button"
                                    className="feed-workspace-load-more feed-workspace-load-more-ghost"
                                    onClick={() => setShowAllEntries(false)}
                                >
                                    收起列表
                                </button>
                            ) : null}
                            {hasMoreEntries ? (
                                <button
                                    type="button"
                                    className="feed-workspace-load-more"
                                    onClick={() => void loadEntries({ append: true })}
                                    disabled={isLoadingMoreEntries}
                                >
                                    {isLoadingMoreEntries ? '加载中...' : '查看更多（加载更多）'}
                                </button>
                            ) : null}
                        </div>
                        <div className="feed-workspace-entry-nav">
                            <button
                                type="button"
                                className="feed-workspace-entry-nav-btn"
                                onClick={() => handleJumpEntry('prev')}
                                disabled={!hasPrevEntry}
                                title="上一篇"
                                aria-label="上一篇"
                            >
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path fill="currentColor" d="m12 6 6 6h-4v6h-4v-6H6l6-6Z" />
                                </svg>
                            </button>
                            <button
                                type="button"
                                className="feed-workspace-entry-nav-btn"
                                onClick={() => handleJumpEntry('next')}
                                disabled={!hasNextEntry}
                                title="下一篇"
                                aria-label="下一篇"
                            >
                                <svg viewBox="0 0 24 24" aria-hidden="true">
                                    <path fill="currentColor" d="m12 18-6-6h4V6h4v6h4l-6 6Z" />
                                </svg>
                            </button>
                        </div>

                        <footer className="feed-workspace-footer">
                            <span>{feedError || feedback}</span>
                            <button
                                type="button"
                                className="feed-workspace-secondary-btn"
                                onClick={() => void handleRefreshFeed(selectedFeedId)}
                                disabled={!selectedFeedId || isRefreshingFeed}
                            >
                                {isRefreshingFeed ? '刷新中...' : '刷新当前订阅源'}
                            </button>
                        </footer>
                    </section>
                </div>
            </div>

            {showAddFeedModal ? (
                <AddFeedModal
                    onClose={() => setShowAddFeedModal(false)}
                    onCreated={(item) => void handleFeedCreated(item)}
                />
            ) : null}
            {showImportModal ? (
                <ImportToNotebookModal
                    notebooks={notebooks}
                    selectedCount={selectedCount}
                    defaultNotebookId={targetNotebookId}
                    isSubmitting={isImporting}
                    onClose={() => setShowImportModal(false)}
                    onConfirm={(notebookId) => void handleBatchImport(notebookId)}
                />
            ) : null}
        </div>
    );
}
