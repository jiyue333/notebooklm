import { useEffect, useMemo, useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import useEscapeToClose from '../hooks/useEscapeToClose';
import { extractClipboardMarkdown } from '../utils/clipboardMarkdown';
import './AddSourceModal.css';

const Ic = {
    web: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95c-.32-1.25-.78-2.45-1.38-3.56 1.84.63 3.37 1.91 4.33 3.56zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56-1.84-.63-3.37-1.91-4.33-3.56zm2.95-8H5.08c.96-1.65 2.49-2.93 4.33-3.56C8.81 5.55 8.35 6.75 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95c-.96 1.65-2.49 2.93-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z" /></svg>,
    fast: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" /><circle cx="12" cy="12" r="2" /></svg>,
    auto: <svg viewBox="0 0 24 24" fill="currentColor"><path d="m12 3 2.44 4.95 5.46.79-3.95 3.84.93 5.42L12 15.43 7.12 18l.93-5.42L4.1 8.74l5.46-.79L12 3z" /></svg>,
    deep: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 1 0 10 10A10.01 10.01 0 0 0 12 2Zm4.23 14.23-1.41 1.41L12 14.83l-2.83 2.81-1.41-1.41L10.59 13 7.77 10.17l1.41-1.41L12 11.59l2.83-2.83 1.41 1.41L13.41 13Z" /></svg>,
    search: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 1 0 16 9.5a6.43 6.43 0 0 0-1.57 4.23l.27.28h.79l5 4.99L20.49 19Zm-6 0A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14Z" /></svg>,
    send: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21 23 12 2.01 3 2 10l15 2-15 2Z" /></svg>,
    upload: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 20h14v-2H5v2Zm7-18-5.5 5.5 1.42 1.42L11 5.83V16h2V5.83l3.08 3.09 1.42-1.42L12 2Z" /></svg>,
    file: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2l-.01 16c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6Zm0 7V3.5L18.5 8H14Z" /></svg>,
    link: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z" /></svg>,
    clipboard: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 1H8a2 2 0 0 0-2 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-1V3a2 2 0 0 0-2-2Zm0 4H8V3h8v2Z" /></svg>,
    cloud: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.35 10.04A7.49 7.49 0 0 0 5.08 7.5 5.996 5.996 0 0 0 6 19h13a5 5 0 0 0 .35-8.96Z" /></svg>,
    close: <svg viewBox="0 0 24 24" fill="currentColor"><path d="m19 6.41-1.41-1.41L12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" /></svg>,
    chevronDown: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>,
    check: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17 4.83 12 3.41 13.41 9 19l12-12-1.41-1.41z" /></svg>,
};

const modeOptions = [
    { id: 'fast', label: 'Fast Research', desc: '快速筛选高相关来源', icon: Ic.fast },
    { id: 'auto', label: 'Auto Research', desc: '平衡速度与覆盖度', icon: Ic.auto },
    { id: 'deep', label: 'Deep Research', desc: '更深入的扩展研究', icon: Ic.deep },
];

export default function AddSourceModal({ notebookId, onClose, onImported, onStartSearch }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [searchMode, setSearchMode] = useState('fast');
    const [webUrl, setWebUrl] = useState('');
    const [webTitle, setWebTitle] = useState('');
    const [textTitle, setTextTitle] = useState('');
    const [textContent, setTextContent] = useState('');
    const [activeQuickAction, setActiveQuickAction] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isStartingSearch, setIsStartingSearch] = useState(false);
    const [showModeMenu, setShowModeMenu] = useState(false);
    const [error, setError] = useState('');
    const fileInputRef = useRef(null);
    const textAreaRef = useRef(null);
    const modeMenuRef = useRef(null);
    const actionLockRef = useRef(false);
    const isBusy = isUploading || isSubmitting || isStartingSearch;

    const currentMode = useMemo(
        () => modeOptions.find((option) => option.id === searchMode) || modeOptions[0],
        [searchMode],
    );

    useEscapeToClose(onClose, !isBusy);

    useEffect(() => {
        const handler = (event) => {
            if (modeMenuRef.current && !modeMenuRef.current.contains(event.target)) {
                setShowModeMenu(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const handleFilesUpload = async (files) => {
        if (!files?.length || actionLockRef.current) {
            return;
        }

        try {
            actionLockRef.current = true;
            setIsUploading(true);
            setError('');
            const detail = await appApi.sources.uploadFiles({ notebookId, files });
            onImported?.(detail);
            onClose();
        } catch (err) {
            setError(err.message || '上传来源失败');
        } finally {
            actionLockRef.current = false;
            setIsUploading(false);
        }
    };

    const handleSearchStart = async () => {
        if (actionLockRef.current) {
            return;
        }
        const normalizedQuery = searchQuery.trim();
        if (!normalizedQuery) {
            setError('请输入搜索关键词');
            return;
        }
        try {
            actionLockRef.current = true;
            setIsStartingSearch(true);
            setError('');
            setShowModeMenu(false);
            await onStartSearch?.({ query: normalizedQuery, mode: searchMode });
            onClose();
        } catch (err) {
            setError(err.message || '启动来源搜索失败');
        } finally {
            actionLockRef.current = false;
            setIsStartingSearch(false);
        }
    };

    const handleCreateSource = async (sourceType) => {
        if (actionLockRef.current) {
            return;
        }
        try {
            actionLockRef.current = true;
            setError('');
            setIsSubmitting(true);

            if (sourceType === 'web') {
                if (!webUrl.trim()) {
                    throw new Error('请输入网站链接');
                }
                const detail = await appApi.sources.create({
                    notebookId,
                    sourceType: 'web',
                    url: webUrl.trim(),
                    title: webTitle.trim() || undefined,
                });
                onImported?.(detail);
                onClose();
                return;
            }

            const normalizedText = textContent.trim();
            if (!normalizedText) {
                throw new Error('请输入要保存的文字内容');
            }

            const detail = await appApi.sources.create({
                notebookId,
                sourceType: 'text',
                title: textTitle.trim() || undefined,
                content: normalizedText,
            });
            onImported?.(detail);
            onClose();
        } catch (err) {
            setError(err.message || '添加来源失败');
        } finally {
            actionLockRef.current = false;
            setIsSubmitting(false);
        }
    };

    const handleDragOver = (event) => {
        event.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (event) => {
        event.preventDefault();
        setIsDragging(false);
        void handleFilesUpload(Array.from(event.dataTransfer.files));
    };

    const insertMarkdownAtCursor = (markdown) => {
        if (!markdown) return;
        const textarea = textAreaRef.current;
        if (!textarea) {
            setTextContent((prev) => `${prev}${prev ? '\n\n' : ''}${markdown}`.trim());
            return;
        }
        const start = textarea.selectionStart ?? textContent.length;
        const end = textarea.selectionEnd ?? textContent.length;
        const nextValue = `${textContent.slice(0, start)}${markdown}${textContent.slice(end)}`;
        setTextContent(nextValue);
        requestAnimationFrame(() => {
            const caret = start + markdown.length;
            textarea.focus();
            textarea.setSelectionRange(caret, caret);
        });
    };

    const handleTextPaste = (event) => {
        const clipboardData = event.clipboardData;
        if (!clipboardData) return;

        const markdown = extractClipboardMarkdown(clipboardData);
        const shouldHandleText = Boolean((clipboardData.getData('text/html') || '').trim());
        if (!shouldHandleText) {
            return;
        }

        event.preventDefault();
        if (markdown.trim()) {
            insertMarkdownAtCursor(markdown);
        }
    };

    const renderInlineForm = () => {
        if (activeQuickAction === 'web') {
            return (
                <div className="add-source-inline-card">
                    <div className="add-source-inline-header">
                        <strong>手动添加网站</strong>
                        <button type="button" className="add-source-inline-close" onClick={() => setActiveQuickAction('')} disabled={isBusy}>
                            {Ic.close}
                        </button>
                    </div>
                    <div className="add-source-inline-field">
                        <span>{Ic.link}</span>
                        <input
                            placeholder="粘贴网站链接"
                            value={webUrl}
                            onChange={(event) => setWebUrl(event.target.value)}
                            disabled={isBusy}
                        />
                    </div>
                    <div className="add-source-inline-field">
                        <span>🏷️</span>
                        <input
                            placeholder="标题（可选，留空自动生成）"
                            value={webTitle}
                            onChange={(event) => setWebTitle(event.target.value)}
                            disabled={isBusy}
                        />
                    </div>
                    <button type="button" className="add-source-inline-primary" onClick={() => void handleCreateSource('web')} disabled={isBusy}>
                        {isSubmitting ? '添加中...' : '添加网站'}
                    </button>
                </div>
            );
        }

        if (activeQuickAction === 'text') {
            return (
                <div className="add-source-inline-card">
                    <div className="add-source-inline-header">
                        <strong>保存复制的文字</strong>
                        <button type="button" className="add-source-inline-close" onClick={() => setActiveQuickAction('')} disabled={isBusy}>
                            {Ic.close}
                        </button>
                    </div>
                    <div className="add-source-inline-field">
                        <span>🏷️</span>
                        <input
                            placeholder="标题（可选，留空自动生成）"
                            value={textTitle}
                            onChange={(event) => setTextTitle(event.target.value)}
                            disabled={isBusy}
                        />
                    </div>
                    <textarea
                        ref={textAreaRef}
                        className="add-source-inline-textarea"
                        placeholder="粘贴网页、Word 或其它富文本内容"
                        value={textContent}
                        onChange={(event) => setTextContent(event.target.value)}
                        onPaste={handleTextPaste}
                        disabled={isBusy}
                    />
                    <button type="button" className="add-source-inline-primary" onClick={() => void handleCreateSource('text')} disabled={isBusy}>
                        {isSubmitting ? '保存中...' : '保存文字来源'}
                    </button>
                </div>
            );
        }

        if (activeQuickAction === 'cloud') {
            return (
                <div className="add-source-inline-card add-source-inline-muted">
                    <div className="add-source-inline-header">
                        <strong>云端硬盘</strong>
                        <button type="button" className="add-source-inline-close" onClick={() => setActiveQuickAction('')} disabled={isBusy}>
                            {Ic.close}
                        </button>
                    </div>
                    <p>暂未开放</p>
                </div>
            );
        }

        return null;
    };

    return (
        <div className="add-source-overlay" onClick={() => { if (!isBusy) onClose(); }}>
            <div className="add-source-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <button type="button" className="add-source-close" onClick={onClose} disabled={isBusy}>
                    {Ic.close}
                </button>

                <h2 className="add-source-title">添加来源</h2>

                <div className="add-source-workbench">
                    <div className="add-source-search-row">
                        <span className="add-source-search-icon">{Ic.search}</span>
                        <input
                            className="add-source-search-input"
                            placeholder="在网络中搜索新来源"
                            value={searchQuery}
                            onChange={(event) => setSearchQuery(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Enter') {
                                    event.preventDefault();
                                    void handleSearchStart();
                                }
                            }}
                            disabled={isBusy}
                        />
                    </div>
                    <div className="add-source-search-controls">
                        <div className="add-source-mode-wrap" ref={modeMenuRef}>
                            <button
                                type="button"
                                className="add-source-pill add-source-pill-select"
                                onClick={() => {
                                    if (!isBusy) setShowModeMenu((current) => !current);
                                }}
                                aria-haspopup="menu"
                                aria-expanded={showModeMenu}
                                disabled={isBusy}
                            >
                                <span className="add-source-pill-icon">{currentMode.icon}</span>
                                <span className="add-source-pill-value">{currentMode.label}</span>
                                <span className="add-source-pill-caret">{Ic.chevronDown}</span>
                            </button>
                            {showModeMenu ? (
                                <div className="add-source-mode-menu" role="menu" aria-label="搜索模式">
                                    {modeOptions.map((option) => (
                                        <button
                                            key={option.id}
                                            type="button"
                                            className={`add-source-mode-option ${searchMode === option.id ? 'active' : ''}`}
                                            onClick={() => {
                                                setSearchMode(option.id);
                                                setShowModeMenu(false);
                                            }}
                                        >
                                            <span className="add-source-mode-option-icon">{option.icon}</span>
                                            <span className="add-source-mode-option-info">
                                                <span className="add-source-mode-option-label">{option.label}</span>
                                                <span className="add-source-mode-option-desc">{option.desc}</span>
                                            </span>
                                            {searchMode === option.id ? (
                                                <span className="add-source-mode-option-check">{Ic.check}</span>
                                            ) : null}
                                        </button>
                                    ))}
                                </div>
                            ) : null}
                        </div>
                        <button type="button" className="add-source-search-submit" onClick={() => void handleSearchStart()} disabled={isBusy}>
                            {isStartingSearch ? <span className="add-source-spinner" /> : Ic.send}
                        </button>
                    </div>
                </div>

                <div
                    className={`add-source-dropzone ${isDragging ? 'dragging' : ''}`}
                    onClick={() => { if (!isBusy) fileInputRef.current?.click(); }}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                >
                    <div className="add-source-dropzone-copy">
                        <strong>或拖放文件</strong>
                        <span>PDF、图片、文档、音频，等等</span>
                    </div>
                    <div className="add-source-quick-actions">
                        <button type="button" className="add-source-quick-btn" onClick={(event) => { event.stopPropagation(); fileInputRef.current?.click(); }} disabled={isBusy}>
                            <span>{Ic.upload}</span>
                            <span>{isUploading ? '上传中...' : '上传文件'}</span>
                        </button>
                        <button type="button" className={`add-source-quick-btn ${activeQuickAction === 'cloud' ? 'active' : ''}`} onClick={(event) => { event.stopPropagation(); setActiveQuickAction((current) => (current === 'cloud' ? '' : 'cloud')); }} disabled={isBusy}>
                            <span>{Ic.cloud}</span>
                            <span>云端硬盘</span>
                        </button>
                        <button type="button" className={`add-source-quick-btn ${activeQuickAction === 'text' ? 'active' : ''}`} onClick={(event) => { event.stopPropagation(); setActiveQuickAction((current) => (current === 'text' ? '' : 'text')); }} disabled={isBusy}>
                            <span>{Ic.clipboard}</span>
                            <span>复制的文字</span>
                        </button>
                    </div>
                </div>

                {renderInlineForm()}
                {error ? <p className="add-source-error">{error}</p> : null}

                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.doc,.docx,.txt,.md,text/plain,text/markdown,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    style={{ display: 'none' }}
                    onChange={(event) => {
                        void handleFilesUpload(Array.from(event.target.files));
                        event.target.value = '';
                    }}
                />
            </div>
        </div>
    );
}
