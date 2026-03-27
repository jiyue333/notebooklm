import { useMemo, useRef, useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './NotebookModal.css';

const notebookPreviewIcon = (
    <svg viewBox="0 0 24 24" fill="currentColor">
        <path d="M6 2h9a3 3 0 0 1 3 3v14a1 1 0 0 1-1.6.8L13 17.4l-3.4 2.4A1 1 0 0 1 8 19V5a3 3 0 0 0-2-2.82V2Zm4 4h5v2h-5V6Zm0 4h5v2h-5v-2Z" />
        <path d="M4 3.5A1.5 1.5 0 0 1 5.5 2h.5v20h-.5A1.5 1.5 0 0 1 4 20.5v-17Z" />
    </svg>
);

function normalizeTags(tags) {
    const deduped = [];
    (tags || []).forEach((item) => {
        const normalized = String(item || '').trim();
        if (!normalized) return;
        if (!deduped.includes(normalized)) {
            deduped.push(normalized);
        }
    });
    return deduped.slice(0, 8);
}

function parseTagInput(value) {
    return normalizeTags(
        String(value || '')
            .split(',')
            .map((item) => item.trim()),
    );
}

export default function NotebookModal({
    mode = 'create',
    notebook,
    onClose,
    onSave,
    onDelete,
    existingTitles = [],
    availableTags = [],
}) {
    const [title, setTitle] = useState(notebook?.title || '');
    const [selectedTags, setSelectedTags] = useState(() => normalizeTags(notebook?.tags || []));
    const [tagInput, setTagInput] = useState('');
    const [showTagSuggestion, setShowTagSuggestion] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState('');
    const tagInputRef = useRef(null);

    useEscapeToClose(onClose, !isSaving);

    const duplicateTitle = useMemo(() => {
        const normalized = title.trim().toLowerCase();
        if (!normalized) return false;
        return existingTitles.some((item) => item.id !== notebook?.id && item.title.trim().toLowerCase() === normalized);
    }, [existingTitles, notebook?.id, title]);

    const addTag = (rawTag) => {
        const nextTag = String(rawTag || '').trim();
        if (!nextTag) return;
        setSelectedTags((prev) => {
            if (prev.includes(nextTag)) return prev;
            if (prev.length >= 8) return prev;
            return [...prev, nextTag];
        });
        setTagInput('');
    };

    const removeTag = (tag) => {
        setSelectedTags((prev) => prev.filter((item) => item !== tag));
    };

    const tagSuggestions = useMemo(() => {
        const normalizedInput = tagInput.trim().toLowerCase();
        const pool = normalizeTags(availableTags);
        const filtered = pool.filter((tag) => !selectedTags.includes(tag));
        if (!normalizedInput) return filtered.slice(0, 8);
        return filtered
            .filter((tag) => tag.toLowerCase().includes(normalizedInput))
            .slice(0, 8);
    }, [availableTags, selectedTags, tagInput]);

    const handleSave = async () => {
        const normalizedTitle = title.trim();
        const pendingTags = parseTagInput(tagInput);
        const finalTags = normalizeTags([...selectedTags, ...pendingTags]);
        if (duplicateTitle) {
            setError('笔记本标题已存在，请换一个名字');
            return;
        }

        try {
            setIsSaving(true);
            setError('');
            await onSave({
                ...notebook,
                title: normalizedTitle || null,
                tags: finalTags,
            });
            onClose();
        } catch (err) {
            setError(err.message || '保存笔记本失败');
        } finally {
            setIsSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!notebook?.id || !onDelete) return;
        try {
            setIsSaving(true);
            setError('');
            await onDelete(notebook.id);
            onClose();
        } catch (err) {
            setError(err.message || '删除笔记本失败');
            setIsSaving(false);
        }
    };

    return (
        <div className="notebook-modal-overlay" onClick={(event) => { if (event.target === event.currentTarget && !isSaving) onClose(); }}>
            <div className="notebook-modal animate-scale-in">
                <div className="notebook-modal-header">
                    <h3>{mode === 'create' ? '新建笔记本' : '编辑笔记本'}</h3>
                    <button className="notebook-modal-close" onClick={onClose} disabled={isSaving}>✕</button>
                </div>

                <div className="notebook-modal-body">
                    <label className="notebook-modal-label">
                        标题
                        <input
                            className="notebook-modal-input"
                            value={title}
                            onChange={(event) => {
                                setTitle(event.target.value);
                                setError('');
                            }}
                            placeholder="留空自动生成标题"
                            autoFocus
                        />
                    </label>

                    <label className="notebook-modal-label">
                        标签
                        <div className="notebook-modal-tag-editor">
                            <div className="notebook-modal-tag-chips">
                                {selectedTags.map((tag) => (
                                    <button
                                        key={tag}
                                        type="button"
                                        className="notebook-modal-tag-chip"
                                        onClick={() => removeTag(tag)}
                                    >
                                        <span>{tag}</span>
                                        <span aria-hidden>✕</span>
                                    </button>
                                ))}
                                <input
                                    ref={tagInputRef}
                                    className="notebook-modal-tag-input"
                                    value={tagInput}
                                    onFocus={() => setShowTagSuggestion(true)}
                                    onBlur={() => {
                                        window.setTimeout(() => setShowTagSuggestion(false), 120);
                                    }}
                                    onChange={(event) => setTagInput(event.target.value)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'Enter' || event.key === ',' || event.key === 'Tab') {
                                            const parsed = parseTagInput(tagInput);
                                            if (parsed.length > 0) {
                                                event.preventDefault();
                                                parsed.forEach((tag) => addTag(tag));
                                            }
                                            return;
                                        }
                                        if (event.key === 'Backspace' && !tagInput.trim() && selectedTags.length > 0) {
                                            removeTag(selectedTags[selectedTags.length - 1]);
                                        }
                                    }}
                                    placeholder={selectedTags.length >= 8 ? '最多 8 个标签' : '输入后回车创建或选择已有标签'}
                                    disabled={selectedTags.length >= 8}
                                />
                            </div>
                            {showTagSuggestion && tagSuggestions.length > 0 ? (
                                <div className="notebook-modal-tag-suggest">
                                    {tagSuggestions.map((tag) => (
                                        <button
                                            key={tag}
                                            type="button"
                                            className="notebook-modal-tag-suggest-item"
                                            onClick={() => {
                                                addTag(tag);
                                                tagInputRef.current?.focus();
                                            }}
                                        >
                                            {tag}
                                        </button>
                                    ))}
                                </div>
                            ) : null}
                        </div>
                    </label>

                    <div className="notebook-modal-preview">
                        <span className="notebook-modal-preview-icon">{notebookPreviewIcon}</span>
                        <div className="notebook-modal-preview-meta">
                            <span className="notebook-modal-preview-title">{title.trim() || '自动生成标题'}</span>
                            <span className="notebook-modal-preview-subtitle">{selectedTags.join(' · ') || '创建后可继续补充标签'}</span>
                        </div>
                    </div>

                    {duplicateTitle ? <p className="notebook-modal-error">笔记本标题已存在，请换一个名字</p> : null}
                    {error ? <p className="notebook-modal-error">{error}</p> : null}
                </div>

                <div className="notebook-modal-footer">
                    {mode === 'edit' && notebook?.id ? (
                        <button className="notebook-modal-delete" onClick={handleDelete} disabled={isSaving}>
                            删除
                        </button>
                    ) : null}
                    <div className="notebook-modal-actions">
                        <button className="notebook-modal-secondary" onClick={onClose} disabled={isSaving}>
                            取消
                        </button>
                        <button className="notebook-modal-primary" onClick={handleSave} disabled={isSaving || duplicateTitle}>
                            {isSaving ? '保存中...' : (mode === 'create' ? '创建笔记本' : '保存更改')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
