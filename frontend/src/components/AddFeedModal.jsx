import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { appApi } from '../services/appApi';
import './AddFeedModal.css';

function isHiddenCategoryTitle(value) {
    return String(value || '').trim().toLowerCase() === 'all';
}

export default function AddFeedModal({ onClose, onCreated }) {
    const [feedUrl, setFeedUrl] = useState('');
    const [categoryName, setCategoryName] = useState('');
    const [categories, setCategories] = useState([]);
    const [showCategorySuggestion, setShowCategorySuggestion] = useState(false);
    const [suggestionDirection, setSuggestionDirection] = useState('down');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState('');
    const categoryEditorRef = useRef(null);

    useEscapeToClose(onClose, !isSubmitting);

    useEffect(() => {
        let cancelled = false;
        const loadCategories = async () => {
            try {
                const items = await appApi.feeds.listCategories();
                if (!cancelled) {
                    setCategories(items || []);
                }
            } catch {
                if (!cancelled) {
                    setCategories([]);
                }
            }
        };
        loadCategories();
        return () => {
            cancelled = true;
        };
    }, []);

    const submitUrl = useMemo(() => feedUrl.trim(), [feedUrl]);
    const normalizedCategories = useMemo(() => {
        const deduped = [];
        (categories || []).forEach((item) => {
            const normalized = String(item?.title || '').trim();
            if (!normalized || isHiddenCategoryTitle(normalized) || deduped.includes(normalized)) return;
            deduped.push(normalized);
        });
        return deduped;
    }, [categories]);
    const categorySuggestions = useMemo(() => {
        const normalizedInput = categoryName.trim().toLowerCase();
        if (!normalizedInput) return normalizedCategories.slice(0, 8);
        return normalizedCategories
            .filter((item) => item.toLowerCase().includes(normalizedInput))
            .slice(0, 8);
    }, [categoryName, normalizedCategories]);

    const updateSuggestionDirection = useCallback(() => {
        const rect = categoryEditorRef.current?.getBoundingClientRect();
        if (!rect) return;
        const spaceBelow = window.innerHeight - rect.bottom;
        setSuggestionDirection(spaceBelow < 220 ? 'up' : 'down');
    }, []);

    const handleCreate = async () => {
        if (!submitUrl) {
            setError('请输入订阅地址');
            return;
        }
        try {
            setError('');
            setIsSubmitting(true);
            const item = await appApi.feeds.create({
                feedUrl: submitUrl,
                categoryName: categoryName.trim() || undefined,
            });
            onCreated?.(item);
            onClose();
        } catch (err) {
            setError(err.message || '添加订阅失败');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="feed-modal-overlay" onClick={onClose}>
            <div className="feed-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <div className="feed-modal-header">
                    <h3>添加订阅源</h3>
                    <button type="button" onClick={onClose}>✕</button>
                </div>

                <div className="feed-modal-body">
                    <label className="feed-modal-label">Feed URL</label>
                    <input
                        className="feed-modal-input"
                        placeholder="https://"
                        value={feedUrl}
                        onChange={(event) => setFeedUrl(event.target.value)}
                        disabled={isSubmitting}
                    />

                    <label className="feed-modal-label">分类</label>
                    <div className="feed-modal-category-editor" ref={categoryEditorRef}>
                        <input
                            className="feed-modal-input"
                            placeholder="输入后回车创建或选择已有分类"
                            value={categoryName}
                            onFocus={() => {
                                updateSuggestionDirection();
                                setShowCategorySuggestion(true);
                            }}
                            onBlur={() => window.setTimeout(() => setShowCategorySuggestion(false), 120)}
                            onChange={(event) => setCategoryName(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter' || event.key === ',' || event.key === 'Tab') {
                                    const normalized = categoryName.trim();
                                    if (normalized) {
                                        event.preventDefault();
                                        setCategoryName(normalized);
                                    }
                                }
                                if (event.key === 'Escape') {
                                    setShowCategorySuggestion(false);
                                }
                            }}
                            disabled={isSubmitting}
                        />
                        {showCategorySuggestion && categorySuggestions.length > 0 ? (
                            <div className={`feed-modal-category-suggest ${suggestionDirection === 'up' ? 'up' : ''}`}>
                                {categorySuggestions.map((item) => (
                                    <button
                                        key={item}
                                        type="button"
                                        className="feed-modal-category-suggest-item"
                                        onClick={() => {
                                            setCategoryName(item);
                                            setShowCategorySuggestion(false);
                                        }}
                                    >
                                        {item}
                                    </button>
                                ))}
                            </div>
                        ) : null}
                    </div>

                    {error ? <p className="feed-modal-error">{error}</p> : null}
                </div>

                <div className="feed-modal-footer">
                    <button type="button" className="feed-modal-secondary" onClick={onClose} disabled={isSubmitting}>取消</button>
                    <button type="button" className="feed-modal-primary" onClick={handleCreate} disabled={isSubmitting}>
                        {isSubmitting ? '订阅中...' : '订阅'}
                    </button>
                </div>
            </div>
        </div>
    );
}
