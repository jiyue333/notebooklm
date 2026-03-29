import { useEffect, useMemo, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { appApi } from '../services/appApi';
import './FeedReaderModal.css';

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

export default function FeedReaderModal({ feed, onClose, onFeedUpdated }) {
    const [entries, setEntries] = useState([]);
    const [selectedEntryId, setSelectedEntryId] = useState(null);
    const [notebooks, setNotebooks] = useState([]);
    const [targetNotebookId, setTargetNotebookId] = useState('');
    const [search, setSearch] = useState('');
    const [meta, setMeta] = useState({ total: 0, unread: 0 });
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [feedback, setFeedback] = useState('');
    const [error, setError] = useState('');

    useEscapeToClose(onClose, !isImporting && !isRefreshing);

    const selectedEntry = useMemo(
        () => entries.find((item) => item.entryId === selectedEntryId) || entries[0] || null,
        [entries, selectedEntryId],
    );

    const loadEntries = async ({ silent = false } = {}) => {
        try {
            if (!silent) {
                setIsLoading(true);
            }
            setError('');
            const payload = await appApi.feeds.listEntries({
                feedId: feed?.id,
                status: 'unread',
                limit: 80,
                offset: 0,
                search: search.trim(),
            });
            setEntries(payload.items || []);
            setMeta(payload.meta || { total: 0, unread: 0 });
            if ((payload.items || []).length > 0) {
                setSelectedEntryId((current) => current || payload.items[0].entryId);
            }
        } catch (err) {
            setError(err.message || '加载订阅内容失败');
        } finally {
            setIsLoading(false);
            setIsRefreshing(false);
        }
    };

    useEffect(() => {
        let cancelled = false;

        const load = async () => {
            try {
                setError('');
                const notebookItems = await appApi.notebooks.list();
                if (cancelled) return;
                setNotebooks(notebookItems || []);
                setTargetNotebookId(notebookItems?.[0]?.id || '');
            } catch (err) {
                if (!cancelled) {
                    setError(err.message || '加载笔记本列表失败');
                }
            }
        };

        load();
        void loadEntries();

        return () => {
            cancelled = true;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [feed?.id]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            void loadEntries({ silent: true });
        }, 260);
        return () => window.clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search]);

    const markEntryRead = async (entryId) => {
        try {
            await appApi.feeds.updateEntriesStatus({ entryIds: [entryId], status: 'read' });
            setEntries((prev) => prev.map((item) => (
                item.entryId === entryId ? { ...item, status: 'read' } : item
            )));
            setMeta((prev) => ({ ...prev, unread: Math.max(0, Number(prev.unread || 0) - 1) }));
            onFeedUpdated?.();
        } catch {
            // noop
        }
    };

    const handleSelectEntry = (entry) => {
        setSelectedEntryId(entry.entryId);
        if (entry.status === 'unread') {
            void markEntryRead(entry.entryId);
        }
    };

    const handleImport = async () => {
        if (!targetNotebookId || !selectedEntry) {
            setError('请选择目标笔记本');
            return;
        }
        try {
            setIsImporting(true);
            setError('');
            const payload = await appApi.feeds.importToNotebook({
                notebookId: targetNotebookId,
                entryIds: [selectedEntry.entryId],
            });
            setFeedback(`已导入 ${payload?.meta?.importedCount || 1} 篇文章`);
            void markEntryRead(selectedEntry.entryId);
        } catch (err) {
            setError(err.message || '导入失败');
        } finally {
            setIsImporting(false);
        }
    };

    const handleMarkAllRead = async () => {
        const ids = entries.map((item) => item.entryId);
        if (ids.length === 0) return;
        try {
            await appApi.feeds.updateEntriesStatus({ entryIds: ids, status: 'read' });
            setEntries((prev) => prev.map((item) => ({ ...item, status: 'read' })));
            setMeta((prev) => ({ ...prev, unread: 0 }));
            onFeedUpdated?.();
        } catch (err) {
            setError(err.message || '批量标记失败');
        }
    };

    const handleRefresh = async () => {
        try {
            setIsRefreshing(true);
            await appApi.feeds.refresh(feed.id);
            await loadEntries({ silent: true });
            onFeedUpdated?.();
        } catch (err) {
            setError(err.message || '刷新失败');
            setIsRefreshing(false);
        }
    };

    const handleToggleBookmark = async () => {
        if (!selectedEntry) return;
        try {
            await appApi.feeds.toggleBookmark(selectedEntry.entryId);
            setEntries((prev) => prev.map((item) => (
                item.entryId === selectedEntry.entryId ? { ...item, starred: !item.starred } : item
            )));
        } catch (err) {
            setError(err.message || '切换星标失败');
        }
    };

    return (
        <div className="feed-reader-overlay" onClick={onClose}>
            <div className="feed-reader-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <header className="feed-reader-header">
                    <div>
                        <h3>{feed?.title || '订阅源阅读器'}</h3>
                        <p>{meta.total || 0} 篇 · {meta.unread || 0} 篇未读</p>
                    </div>
                    <div className="feed-reader-header-actions">
                        <input
                            className="feed-reader-search"
                            placeholder="搜索标题或摘要"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                        />
                        <button type="button" onClick={handleToggleBookmark} disabled={!selectedEntry}>☆</button>
                        <button type="button" onClick={onClose}>✕</button>
                    </div>
                </header>

                <div className="feed-reader-body">
                    <aside className="feed-reader-list">
                        {isLoading ? <p className="feed-reader-empty">加载中...</p> : null}
                        {!isLoading && entries.length === 0 ? <p className="feed-reader-empty">暂无文章</p> : null}
                        {entries.map((entry) => (
                            <button
                                key={entry.entryId}
                                type="button"
                                className={`feed-entry-item ${selectedEntry?.entryId === entry.entryId ? 'active' : ''}`}
                                onClick={() => handleSelectEntry(entry)}
                            >
                                <div className="feed-entry-item-title-row">
                                    {entry.status === 'unread' ? <span className="feed-entry-unread-dot" /> : null}
                                    <strong>{entry.title}</strong>
                                </div>
                                <span>{entry.feedTitle || feed?.title || ''}</span>
                                <span>{formatTime(entry.publishedAt)}</span>
                            </button>
                        ))}
                    </aside>

                    <section className="feed-reader-content">
                        {selectedEntry ? (
                            <>
                                <h4>{selectedEntry.title}</h4>
                                <p className="feed-reader-meta">
                                    {selectedEntry.author ? `${selectedEntry.author} · ` : ''}
                                    {formatTime(selectedEntry.publishedAt)}
                                </p>
                                <div className="feed-reader-summary">
                                    <p>{selectedEntry.aiSummary || selectedEntry.contentPreview || '暂无摘要'}</p>
                                </div>
                                <div className="feed-reader-import-row">
                                    <select
                                        value={targetNotebookId}
                                        onChange={(event) => setTargetNotebookId(event.target.value)}
                                    >
                                        {notebooks.map((item) => (
                                            <option key={item.id} value={item.id}>{item.title}</option>
                                        ))}
                                    </select>
                                    <button type="button" onClick={handleImport} disabled={isImporting || !targetNotebookId}>
                                        {isImporting ? '导入中...' : '导入到笔记本'}
                                    </button>
                                    <button
                                        type="button"
                                        className="feed-reader-link-btn"
                                        onClick={() => window.open(selectedEntry.url, '_blank', 'noopener,noreferrer')}
                                    >
                                        打开原文
                                    </button>
                                </div>
                            </>
                        ) : (
                            <p className="feed-reader-empty">请选择左侧文章</p>
                        )}
                    </section>
                </div>

                <footer className="feed-reader-footer">
                    <div>{feedback || error}</div>
                    <div className="feed-reader-footer-actions">
                        <button type="button" onClick={handleMarkAllRead}>全部标记已读</button>
                        <button type="button" onClick={handleRefresh} disabled={isRefreshing}>
                            {isRefreshing ? '刷新中...' : '刷新'}
                        </button>
                    </div>
                </footer>
            </div>
        </div>
    );
}
