import { useEffect, useMemo, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { appApi } from '../services/appApi';
import './ImportRssModal.css';

const Ic = {
    search: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 1 0 16 9.5a6.43 6.43 0 0 0-1.57 4.23l.27.28h.79l5 4.99L20.49 19Zm-6 0A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14Z" />
        </svg>
    ),
    rss: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M6.18 17.82a2.18 2.18 0 1 1 0-4.36 2.18 2.18 0 0 1 0 4.36ZM4 4v3a13 13 0 0 1 13 13h3A16 16 0 0 0 4 4Zm0 6v3a7 7 0 0 1 7 7h3a10 10 0 0 0-10-10Z" />
        </svg>
    ),
    check: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M9 16.17 4.83 12 3.41 13.41 9 19l12-12-1.41-1.41z" />
        </svg>
    ),
    article: (
        <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm2 4v2h8V8H8Zm0 4v2h8v-2H8Zm0 4v2h5v-2H8Z" />
        </svg>
    ),
};

function getEntryPreview(entry) {
    const preview = String(entry?.contentPreview || '').trim();
    if (preview) return preview;
    const summaryText = String(entry?.summaryText || '').trim();
    if (summaryText) return summaryText;
    const summary = String(entry?.aiSummary || '').trim();
    if (summary && summary !== '暂无摘要') return summary;
    return '暂无摘要';
}

const FILTER_OPTIONS = [
    { id: 'unread', label: '仅未读', icon: Ic.rss },
    { id: 'all', label: '全部文章', icon: Ic.article },
];

function matchesEntry(entry, keyword) {
    if (!keyword) return true;
    const haystack = [
        entry?.title,
        entry?.contentPreview,
        entry?.summaryText,
        entry?.author,
        entry?.feedTitle,
    ]
        .map((item) => String(item || '').toLowerCase())
        .join(' ');
    return haystack.includes(keyword);
}

export default function ImportRssModal({ notebookId, onClose, onImported }) {
    const [entries, setEntries] = useState([]);
    const [feeds, setFeeds] = useState([]);
    const [selectedIds, setSelectedIds] = useState([]);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('unread');
    const [feedFilter, setFeedFilter] = useState('all');
    const [isLoading, setIsLoading] = useState(true);
    const [isLoadingFeeds, setIsLoadingFeeds] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [error, setError] = useState('');

    useEscapeToClose(onClose, !isImporting);

    const loadFeeds = async () => {
        try {
            setIsLoadingFeeds(true);
            const payload = await appApi.feeds.list();
            setFeeds(payload.items || []);
        } catch {
            setFeeds([]);
        } finally {
            setIsLoadingFeeds(false);
        }
    };

    const loadEntries = async ({ silent = false } = {}) => {
        try {
            if (!silent) {
                setIsLoading(true);
            }
            setError('');
            const payload = await appApi.feeds.listEntries({
                feedId: feedFilter === 'all' ? null : feedFilter,
                status: statusFilter,
                limit: 100,
                offset: 0,
            });
            setEntries(payload.items || []);
        } catch (err) {
            setError(err.message || '加载订阅文章失败');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        void loadFeeds();
        void loadEntries();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        void loadEntries({ silent: true });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [statusFilter, feedFilter]);

    const normalizedSearch = search.trim().toLowerCase();
    const filteredEntries = useMemo(
        () => entries.filter((entry) => matchesEntry(entry, normalizedSearch)),
        [entries, normalizedSearch],
    );
    const groupedEntries = useMemo(() => {
        const groups = new Map();
        filteredEntries.forEach((entry) => {
            const key = String(entry.feedId || entry.feedTitle || 'rss:unknown');
            if (!groups.has(key)) {
                groups.set(key, {
                    key,
                    feedTitle: entry.feedTitle || '订阅源',
                    items: [],
                });
            }
            groups.get(key).items.push(entry);
        });
        return Array.from(groups.values());
    }, [filteredEntries]);
    const selectedCount = selectedIds.length;
    const allChecked = useMemo(
        () => filteredEntries.length > 0 && filteredEntries.every((entry) => selectedIds.includes(entry.entryId)),
        [filteredEntries, selectedIds],
    );

    const toggleChecked = (entryId) => {
        setSelectedIds((prev) => (
            prev.includes(entryId)
                ? prev.filter((id) => id !== entryId)
                : [...prev, entryId]
        ));
    };

    const toggleSelectAll = () => {
        if (allChecked) {
            setSelectedIds([]);
            return;
        }
        setSelectedIds(filteredEntries.map((item) => item.entryId));
    };

    const handleImport = async () => {
        if (selectedIds.length === 0) {
            setError('请先选择至少一篇文章');
            return;
        }
        try {
            setError('');
            setIsImporting(true);
            const payload = await appApi.feeds.importToNotebook({ notebookId, entryIds: selectedIds });
            onImported?.(payload.item);
            onClose();
        } catch (err) {
            setError(err.message || '导入失败');
        } finally {
            setIsImporting(false);
        }
    };

    useEffect(() => {
        const idSet = new Set(filteredEntries.map((entry) => entry.entryId));
        setSelectedIds((previous) => previous.filter((id) => idSet.has(id)));
    }, [filteredEntries]);

    const feedFilters = useMemo(() => {
        const map = new Map();
        feeds.forEach((feed) => {
            const id = String(feed?.id || '').trim();
            if (!id) return;
            map.set(id, {
                id,
                title: String(feed?.title || '未命名订阅源'),
                unreadCount: Number(feed?.unreadCount || 0),
            });
        });
        if (map.size === 0) {
            entries.forEach((entry) => {
                const id = String(entry?.feedId || '').trim();
                if (!id) return;
                if (!map.has(id)) {
                    map.set(id, {
                        id,
                        title: String(entry?.feedTitle || '订阅源'),
                        unreadCount: 0,
                    });
                }
            });
        }
        return Array.from(map.values());
    }, [entries, feeds]);

    return (
        <section className="rss-import-panel">
            <header className="rss-import-header">
                <div className="rss-import-header-copy">
                    <span className="rss-import-header-icon">{Ic.rss}</span>
                    <h3>从订阅源导入</h3>
                </div>
                <button type="button" className="rss-import-close" onClick={onClose}>关闭</button>
            </header>

            <div className="rss-import-body">
                <div className="rss-import-toolbar">
                    <label className="rss-import-search-wrap">
                        <span>{Ic.search}</span>
                        <input
                            className="rss-import-search"
                            placeholder="搜索 RSS 条目"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                        />
                    </label>
                    <div className="rss-import-filter-group" role="tablist" aria-label="文章范围">
                        {FILTER_OPTIONS.map((option) => (
                            <button
                                key={option.id}
                                type="button"
                                className={`rss-import-filter-btn ${statusFilter === option.id ? 'active' : ''}`}
                                onClick={() => setStatusFilter(option.id)}
                                aria-pressed={statusFilter === option.id}
                            >
                                <span>{option.icon}</span>
                                <span>{option.label}</span>
                            </button>
                        ))}
                    </div>
                    <button type="button" className="rss-import-secondary" onClick={toggleSelectAll}>
                        {allChecked ? '取消全选' : '全选当前结果'}
                    </button>
                </div>

                <div className="rss-import-feed-filters" role="tablist" aria-label="订阅源筛选">
                    <button
                        type="button"
                        className={`rss-import-feed-btn ${feedFilter === 'all' ? 'active' : ''}`}
                        onClick={() => setFeedFilter('all')}
                        aria-pressed={feedFilter === 'all'}
                    >
                        全部订阅源
                    </button>
                    {feedFilters.map((feed) => (
                        <button
                            key={feed.id}
                            type="button"
                            className={`rss-import-feed-btn ${feedFilter === feed.id ? 'active' : ''}`}
                            onClick={() => setFeedFilter(feed.id)}
                            aria-pressed={feedFilter === feed.id}
                        >
                            <span className="rss-import-feed-title">{feed.title}</span>
                            <span className="rss-import-feed-count">{feed.unreadCount}</span>
                        </button>
                    ))}
                </div>

                <div className="rss-import-meta">
                    <span>
                        {statusFilter === 'unread' ? '仅看未读文章' : '显示全部文章'}
                        {' · '}
                        {filteredEntries.length} / {entries.length} 篇候选文章
                        {isLoadingFeeds ? ' · 同步订阅源中...' : ''}
                    </span>
                    <span>{selectedCount > 0 ? `已选择 ${selectedCount} 篇` : '选择后即可导入'}</span>
                </div>

                <div className="rss-import-list">
                    {isLoading ? <p className="rss-import-empty">加载中...</p> : null}
                    {!isLoading && filteredEntries.length === 0 ? (
                        <div className="rss-import-empty rss-import-empty-card">
                            <span className="rss-import-empty-icon">{Ic.rss}</span>
                            <strong>暂无可导入条目</strong>
                            <span>{statusFilter === 'unread' ? '当前没有未读文章，可以切到“全部文章”继续挑选。' : '先在订阅源面板添加订阅，或者换一个关键词试试。'}</span>
                            {statusFilter === 'unread' ? (
                                <button
                                    type="button"
                                    className="rss-import-secondary rss-import-empty-action"
                                    onClick={() => setStatusFilter('all')}
                                >
                                    查看全部文章
                                </button>
                            ) : null}
                        </div>
                    ) : null}
                    {groupedEntries.map((group) => (
                        <section className="rss-import-group" key={group.key}>
                            {feedFilter === 'all' ? <h4 className="rss-import-group-title">{group.feedTitle}</h4> : null}
                            {group.items.map((entry) => {
                                const preview = getEntryPreview(entry);
                                const checked = selectedIds.includes(entry.entryId);
                                return (
                                    <label key={entry.entryId} className={`rss-import-item ${checked ? 'checked' : ''}`}>
                                        <input
                                            className="rss-import-item-toggle"
                                            type="checkbox"
                                            checked={checked}
                                            onChange={() => toggleChecked(entry.entryId)}
                                        />
                                        <span className="rss-import-item-content">
                                            <span className="rss-import-item-meta">
                                                <span>{entry.feedTitle || '订阅源'}</span>
                                                <span>{entry.author || '未知作者'}</span>
                                            </span>
                                            <strong>{entry.title}</strong>
                                            <span className="rss-import-item-preview">{preview}</span>
                                        </span>
                                        {checked ? <span className="rss-import-item-check">{Ic.check}</span> : null}
                                    </label>
                                );
                            })}
                        </section>
                    ))}
                </div>
            </div>

            <footer className="rss-import-footer">
                <span>{error || `将导入到当前笔记本`}</span>
                <div>
                    <button type="button" className="rss-import-secondary" onClick={onClose} disabled={isImporting}>取消</button>
                    <button type="button" className="rss-import-primary" onClick={handleImport} disabled={isImporting || selectedCount === 0}>
                        {isImporting ? '导入中...' : '导入选中文章'}
                    </button>
                </div>
            </footer>
        </section>
    );
}
