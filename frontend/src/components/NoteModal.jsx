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

const TOOLBAR_ACTIONS = [
    { label: 'H1', token: '# ' },
    { label: 'H2', token: '## ' },
    { label: '加粗', token: '**文本**' },
    { label: '列表', token: '- 列表项' },
    { label: '链接', token: '[链接文本](https://example.com)' },
    { label: '代码块', token: '```\n代码\n```' },
];

export default function NoteModal({ note, onClose, onSave, onDelete, onExport }) {
    const [title, setTitle] = useState(note?.title || '');
    const [content, setContent] = useState(note?.content || '');
    const [tagsText, setTagsText] = useState(Array.isArray(note?.tags) ? note.tags.join(', ') : '');
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState('');
    const savingRef = useRef(false);
    const editorRef = useRef(null);

    useEscapeToClose(onClose, !isSaving);

    const insertSnippet = (snippet) => {
        const textarea = editorRef.current;
        if (!textarea) {
            setContent((prev) => `${prev}${prev ? '\n' : ''}${snippet}`);
            return;
        }
        const start = textarea.selectionStart ?? content.length;
        const end = textarea.selectionEnd ?? content.length;
        const nextValue = `${content.slice(0, start)}${snippet}${content.slice(end)}`;
        setContent(nextValue);
        requestAnimationFrame(() => {
            const cursor = start + snippet.length;
            textarea.focus();
            textarea.setSelectionRange(cursor, cursor);
        });
    };

    const handleSave = async () => {
        if (savingRef.current) return;
        try {
            savingRef.current = true;
            setIsSaving(true);
            setError('');
            await onSave({ ...note, title: title.trim() || '无标题笔记', content, tags: tagsText.split(',').map((item) => item.trim()).filter(Boolean) });
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
        <div className="note-modal-overlay" onClick={(event) => { if (!isSaving && event.target === event.currentTarget) onClose(); }}>
            <div className="note-modal">
                <div className="note-modal-header">
                    <input
                        className="note-modal-title-input"
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                        placeholder="笔记标题..."
                    />
                    <div className="note-modal-actions">
                        {note?.id && onExport ? (
                            <button className="note-modal-tab" onClick={() => onExport(note.id)} title="导出 Markdown">导出</button>
                        ) : null}
                        {note?.id ? (
                            <button className="note-modal-del-btn" onClick={handleDelete} title="删除笔记" disabled={isSaving}>
                                {Ic.del}
                            </button>
                        ) : null}
                        <button className="note-modal-close-btn" onClick={onClose} title="关闭" disabled={isSaving}>
                            {Ic.close}
                        </button>
                    </div>
                </div>
                <div className="note-modal-toolbar">
                    <input className="note-modal-tag-input" value={tagsText} onChange={(event) => setTagsText(event.target.value)} placeholder="标签：如 调研, 摘要, 引用" />
                    {TOOLBAR_ACTIONS.map((action) => (
                        <button key={action.label} type="button" className="note-modal-tool-btn" onClick={() => insertSnippet(action.token)}>
                            {action.label}
                        </button>
                    ))}
                </div>
                <div className="note-modal-body note-modal-split">
                    <div className="note-modal-pane">
                        <div className="note-modal-pane-header">
                            {Ic.edit}<span>编辑</span>
                        </div>
                        <textarea
                            ref={editorRef}
                            className="note-modal-editor"
                            value={content}
                            onChange={(event) => setContent(event.target.value)}
                            placeholder="在这里输入笔记内容... 支持 Markdown 格式"
                            autoFocus
                        />
                    </div>
                    <div className="note-modal-pane note-modal-preview-pane">
                        <div className="note-modal-pane-header">
                            {Ic.preview}<span>实时预览</span>
                        </div>
                        <div className="note-modal-preview">
                            {content ? (
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                            ) : (
                                <p className="note-modal-empty">开始输入后，这里会实时显示预览效果</p>
                            )}
                        </div>
                    </div>
                </div>
                {error ? <div className="note-modal-empty">{error}</div> : null}
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
