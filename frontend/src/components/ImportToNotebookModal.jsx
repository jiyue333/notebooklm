import { useMemo, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './ImportToNotebookModal.css';

function normalizeTags(tags) {
    const deduped = [];
    (tags || []).forEach((item) => {
        const normalized = String(item || '').trim();
        if (!normalized || deduped.includes(normalized)) return;
        deduped.push(normalized);
    });
    return deduped;
}

export default function ImportToNotebookModal({
    notebooks = [],
    selectedCount = 0,
    defaultNotebookId = '',
    isSubmitting = false,
    onClose,
    onConfirm,
}) {
    const [query, setQuery] = useState('');
    const [activeTag, setActiveTag] = useState('');
    const [selectedNotebookId, setSelectedNotebookId] = useState(defaultNotebookId || notebooks?.[0]?.id || '');

    useEscapeToClose(onClose, !isSubmitting);
    const effectiveSelectedNotebookId = selectedNotebookId || defaultNotebookId || notebooks?.[0]?.id || '';

    const allTags = useMemo(() => {
        const tags = [];
        notebooks.forEach((item) => {
            normalizeTags(item.tags || []).forEach((tag) => {
                if (!tags.includes(tag)) tags.push(tag);
            });
        });
        return tags.sort((a, b) => a.localeCompare(b, 'zh-CN'));
    }, [notebooks]);

    const filteredNotebooks = useMemo(() => {
        const keyword = query.trim().toLowerCase();
        return notebooks.filter((item) => {
            const tags = normalizeTags(item.tags || []);
            if (activeTag && !tags.includes(activeTag)) return false;
            if (!keyword) return true;
            if (String(item.title || '').toLowerCase().includes(keyword)) return true;
            return tags.some((tag) => tag.toLowerCase().includes(keyword));
        });
    }, [activeTag, notebooks, query]);

    const selectedNotebook = useMemo(
        () => notebooks.find((item) => item.id === effectiveSelectedNotebookId) || null,
        [effectiveSelectedNotebookId, notebooks],
    );

    return (
        <div className="import-notebook-overlay" onClick={onClose}>
            <div className="import-notebook-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <header className="import-notebook-header">
                    <div>
                        <h3>导入到笔记本</h3>
                        <p>已选择 {selectedCount} 篇文章</p>
                    </div>
                    <button type="button" onClick={onClose}>✕</button>
                </header>

                <div className="import-notebook-toolbar">
                    <input
                        className="import-notebook-search"
                        placeholder="搜索笔记本标题或标签"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        autoFocus
                    />
                    <div className="import-notebook-tags">
                        <button
                            type="button"
                            className={`import-notebook-tag ${!activeTag ? 'active' : ''}`}
                            onClick={() => setActiveTag('')}
                        >
                            全部标签
                        </button>
                        {allTags.map((tag) => (
                            <button
                                key={tag}
                                type="button"
                                className={`import-notebook-tag ${activeTag === tag ? 'active' : ''}`}
                                onClick={() => setActiveTag((current) => (current === tag ? '' : tag))}
                            >
                                {tag}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="import-notebook-list">
                    {filteredNotebooks.length === 0 ? <p className="import-notebook-empty">没有符合条件的笔记本</p> : null}
                    {filteredNotebooks.map((item) => (
                        <button
                            key={item.id}
                            type="button"
                            className={`import-notebook-item ${effectiveSelectedNotebookId === item.id ? 'active' : ''}`}
                            onClick={() => setSelectedNotebookId(item.id)}
                        >
                            <div className="import-notebook-item-main">
                                <strong>{item.title}</strong>
                                <span>{item.sourceCount || 0} 个来源</span>
                            </div>
                            <div className="import-notebook-item-tags">
                                {normalizeTags(item.tags || []).slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
                            </div>
                        </button>
                    ))}
                </div>

                <footer className="import-notebook-footer">
                    <div>
                        目标笔记本：{selectedNotebook?.title || '未选择'}
                    </div>
                    <div className="import-notebook-actions">
                        <button type="button" className="import-notebook-secondary" onClick={onClose} disabled={isSubmitting}>取消</button>
                        <button
                            type="button"
                            className="import-notebook-primary"
                            disabled={!effectiveSelectedNotebookId || isSubmitting}
                            onClick={() => onConfirm?.(effectiveSelectedNotebookId)}
                        >
                            {isSubmitting ? '导入中...' : `导入 ${selectedCount} 篇`}
                        </button>
                    </div>
                </footer>
            </div>
        </div>
    );
}
