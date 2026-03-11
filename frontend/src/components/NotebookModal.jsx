import { useState } from 'react';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './NotebookModal.css';

export default function NotebookModal({ mode = 'create', notebook, onClose, onSave, onDelete }) {
    const [title, setTitle] = useState(notebook?.title || '');
    const [emoji, setEmoji] = useState(notebook?.emoji || '📒');
    const [color, setColor] = useState(notebook?.color || '#8B7355');
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState('');

    useEscapeToClose(onClose, !isSaving);

    const handleSave = async () => {
        try {
            setIsSaving(true);
            setError('');
            await onSave({
                ...notebook,
                title: title.trim() || 'Untitled notebook',
                emoji: emoji.trim() || '📒',
                color,
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
        <div className="notebook-modal-overlay" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
            <div className="notebook-modal">
                <div className="notebook-modal-header">
                    <h3>{mode === 'create' ? '新建笔记本' : '编辑笔记本'}</h3>
                    <button className="notebook-modal-close" onClick={onClose}>✕</button>
                </div>

                <div className="notebook-modal-body">
                    <label className="notebook-modal-label">
                        标题
                        <input
                            className="notebook-modal-input"
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            placeholder="输入笔记本标题"
                            autoFocus
                        />
                    </label>

                    <div className="notebook-modal-row">
                        <label className="notebook-modal-label notebook-modal-field-sm">
                            Emoji
                            <input
                                className="notebook-modal-input"
                                value={emoji}
                                onChange={(event) => setEmoji(event.target.value)}
                                placeholder="📒"
                                maxLength={4}
                            />
                        </label>

                        <label className="notebook-modal-label notebook-modal-field-sm">
                            主题色
                            <div className="notebook-modal-color-row">
                                <input
                                    className="notebook-modal-color"
                                    type="color"
                                    value={color}
                                    onChange={(event) => setColor(event.target.value)}
                                />
                                <input
                                    className="notebook-modal-input"
                                    value={color}
                                    onChange={(event) => setColor(event.target.value)}
                                    placeholder="#8B7355"
                                />
                            </div>
                        </label>
                    </div>

                    <div className="notebook-modal-preview" style={{ background: color }}>
                        <span className="notebook-modal-preview-emoji">{emoji || '📒'}</span>
                        <div className="notebook-modal-preview-meta">
                            <span className="notebook-modal-preview-title">{title.trim() || 'Untitled notebook'}</span>
                            <span className="notebook-modal-preview-subtitle">预览卡片标题</span>
                        </div>
                    </div>

                    {error && <p className="notebook-modal-error">{error}</p>}
                </div>

                <div className="notebook-modal-footer">
                    {mode === 'edit' && notebook?.id && (
                        <button className="notebook-modal-delete" onClick={handleDelete} disabled={isSaving}>
                            删除
                        </button>
                    )}
                    <div className="notebook-modal-actions">
                        <button className="notebook-modal-secondary" onClick={onClose} disabled={isSaving}>
                            取消
                        </button>
                        <button className="notebook-modal-primary" onClick={handleSave} disabled={isSaving}>
                            {isSaving ? '保存中...' : (mode === 'create' ? '创建笔记本' : '保存更改')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
