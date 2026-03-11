import { useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './NoteModal.css';

const Ic = {
    close: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" /></svg>,
    edit: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    preview: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z" /></svg>,
    del: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" /></svg>,
};

export default function NoteModal({ note, onClose, onSave, onDelete }) {
    const [title, setTitle] = useState(note?.title || '');
    const [content, setContent] = useState(note?.content || '');
    const [mode, setMode] = useState(note?.id ? 'preview' : 'edit'); // 'edit' | 'preview'
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState('');
    const savingRef = useRef(false);

    useEscapeToClose(onClose, !isSaving);

    const handleSave = async () => {
        if (savingRef.current) return;
        try {
            savingRef.current = true;
            setIsSaving(true);
            setError('');
            await onSave({ ...note, title: title.trim() || '无标题笔记', content });
            onClose();
        } catch (err) {
            setError(err.message || '保存笔记失败');
        } finally {
            savingRef.current = false;
            setIsSaving(false);
        }
    };

    const handleDelete = async () => {
        if (savingRef.current) return;
        if (onDelete && note?.id) {
            try {
                savingRef.current = true;
                setIsSaving(true);
                setError('');
                await onDelete(note.id);
            } catch (err) {
                setError(err.message || '删除笔记失败');
                savingRef.current = false;
                setIsSaving(false);
                return;
            }
        }
        savingRef.current = false;
        setIsSaving(false);
        onClose();
    };

    return (
        <div className="note-modal-overlay" onClick={(e) => { if (!isSaving && e.target === e.currentTarget) onClose(); }}>
            <div className="note-modal">
                <div className="note-modal-header">
                    <input
                        className="note-modal-title-input"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                        placeholder="笔记标题..."
                        readOnly={mode === 'preview'}
                    />
                    <div className="note-modal-actions">
                        <button
                            className={`note-modal-tab ${mode === 'edit' ? 'active' : ''}`}
                            onClick={() => setMode('edit')}
                            title="编辑"
                            disabled={isSaving}
                        >
                            {Ic.edit}
                            <span>编辑</span>
                        </button>
                        <button
                            className={`note-modal-tab ${mode === 'preview' ? 'active' : ''}`}
                            onClick={() => setMode('preview')}
                            title="预览"
                            disabled={isSaving}
                        >
                            {Ic.preview}
                            <span>预览</span>
                        </button>
                        {note?.id && (
                            <button className="note-modal-del-btn" onClick={handleDelete} title="删除笔记" disabled={isSaving}>
                                {Ic.del}
                            </button>
                        )}
                        <button className="note-modal-close-btn" onClick={onClose} title="关闭" disabled={isSaving}>
                            {Ic.close}
                        </button>
                    </div>
                </div>
                <div className="note-modal-body">
                    {mode === 'edit' ? (
                        <textarea
                            className="note-modal-editor"
                            value={content}
                            onChange={(e) => setContent(e.target.value)}
                            placeholder="在这里输入笔记内容... 支持 Markdown 格式"
                            autoFocus={mode === 'edit'}
                        />
                    ) : (
                        <div className="note-modal-preview">
                            {content ? (
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                            ) : (
                                <p className="note-modal-empty">暂无内容，切换到编辑模式开始写作</p>
                            )}
                        </div>
                    )}
                </div>
                {error && <div className="note-modal-empty">{error}</div>}
                <div className="note-modal-footer">
                    <button className="note-modal-cancel-btn" onClick={onClose} disabled={isSaving}>取消</button>
                    <button className="note-modal-save-btn" onClick={handleSave} disabled={isSaving}>
                        {isSaving ? '保存中...' : '保存'}
                    </button>
                </div>
            </div>
        </div>
    );
}
