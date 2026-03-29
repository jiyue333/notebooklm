import { useEffect, useMemo, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { appApi } from '../services/appApi';
import './ImportRssModal.css';

export default function ImportRssModal({ notebookId, onClose, onImported }) {
    const [entries, setEntries] = useState([]);
    const [selectedIds, setSelectedIds] = useState([]);
    const [search, setSearch] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [isImporting, setIsImporting] = useState(false);
    const [error, setError] = useState('');

    useEscapeToClose(onClose, !isImporting);

    const loadEntries = async ({ silent = false } = {}) => {
        try {
            if (!silent) {
                setIsLoading(true);
            }
            setError('');
            const payload = await appApi.feeds.listEntries({
                status: 'unread',
                limit: 100,
                offset: 0,
                search: search.trim(),
            });
            setEntries(payload.items || []);
            setSelectedIds([]);
        } catch (err) {
            setError(err.message || '加载订阅文章失败');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        void loadEntries();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            void loadEntries({ silent: true });
        }, 260);
        return () => window.clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search]);

    const selectedCount = selectedIds.length;

    const allChecked = useMemo(
        () => entries.length > 0 && selectedIds.length === entries.length,
        [entries.length, selectedIds.length],
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
        setSelectedIds(entries.map((item) => item.entryId));
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

    return (
        <div className="rss-import-overlay" onClick={onClose}>
            <div className="rss-import-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <header className="rss-import-header">
                    <h3>从订阅源导入</h3>
                    <button type="button" onClick={onClose}>✕</button>
                </header>

                <div className="rss-import-toolbar">
                    <input
                        className="rss-import-search"
                        placeholder="搜索 RSS 条目"
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                    />
                    <button type="button" className="rss-import-secondary" onClick={toggleSelectAll}>
                        {allChecked ? '取消全选' : '全选'}
                    </button>
                </div>

                <div className="rss-import-list">
                    {isLoading ? <p className="rss-import-empty">加载中...</p> : null}
                    {!isLoading && entries.length === 0 ? <p className="rss-import-empty">暂无可导入条目</p> : null}
                    {entries.map((entry) => (
                        <label key={entry.entryId} className="rss-import-item">
                            <input
                                type="checkbox"
                                checked={selectedIds.includes(entry.entryId)}
                                onChange={() => toggleChecked(entry.entryId)}
                            />
                            <span className="rss-import-item-content">
                                <strong>{entry.title}</strong>
                                <span>{entry.feedTitle || '订阅源'} · {entry.aiSummary || entry.contentPreview || '暂无摘要'}</span>
                            </span>
                        </label>
                    ))}
                </div>

                <footer className="rss-import-footer">
                    <span>{error || `已选择 ${selectedCount} 篇`}</span>
                    <div>
                        <button type="button" className="rss-import-secondary" onClick={onClose} disabled={isImporting}>取消</button>
                        <button type="button" className="rss-import-primary" onClick={handleImport} disabled={isImporting || selectedCount === 0}>
                            {isImporting ? '导入中...' : '导入'}
                        </button>
                    </div>
                </footer>
            </div>
        </div>
    );
}
