import { useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import useEscapeToClose from '../hooks/useEscapeToClose';
import './AddSourceModal.css';

export default function AddSourceModal({ notebookId, onClose, onImported }) {
    const [activeTab, setActiveTab] = useState('file');
    const [webUrl, setWebUrl] = useState('');
    const [webTitle, setWebTitle] = useState('');
    const [textTitle, setTextTitle] = useState('');
    const [textContent, setTextContent] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [error, setError] = useState('');
    const fileInputRef = useRef(null);
    const actionLockRef = useRef(false);
    const isBusy = isUploading || isSubmitting;

    useEscapeToClose(onClose, !isBusy);

    const handleFilesUpload = async (files) => {
        if (!files?.length || actionLockRef.current) return;

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

    const handleCreateSource = async () => {
        if (actionLockRef.current) return;
        try {
            actionLockRef.current = true;
            setError('');
            setIsSubmitting(true);

            if (activeTab === 'web') {
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

            if (!textContent.trim()) {
                throw new Error('请输入要保存的文字内容');
            }
            const detail = await appApi.sources.create({
                notebookId,
                sourceType: 'text',
                title: textTitle.trim() || '粘贴文字来源',
                content: textContent.trim(),
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
        handleFilesUpload(Array.from(event.dataTransfer.files));
    };

    return (
        <div className="add-source-overlay" onClick={() => { if (!isBusy) onClose(); }}>
            <div className="add-source-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <button className="add-source-close" onClick={onClose} disabled={isBusy}>✕</button>

                <h2 className="add-source-title">添加来源</h2>
                <p className="add-source-subtitle">上传文档、添加网站，或保存你粘贴的文字内容</p>

                <div className="add-source-tags">
                    <button
                        className={`add-source-tag ${activeTab === 'file' ? 'active' : ''}`}
                        onClick={() => setActiveTab('file')}
                        disabled={isBusy}
                    >
                        📁 上传文件
                    </button>
                    <button
                        className={`add-source-tag ${activeTab === 'web' ? 'active' : ''}`}
                        onClick={() => setActiveTab('web')}
                        disabled={isBusy}
                    >
                        🌐 网站
                    </button>
                    <button
                        className={`add-source-tag ${activeTab === 'text' ? 'active' : ''}`}
                        onClick={() => setActiveTab('text')}
                        disabled={isBusy}
                    >
                        📋 复制的文字
                    </button>
                </div>

                {activeTab === 'file' && (
                    <>
                        <div
                            className={`add-source-dropzone ${isDragging ? 'dragging' : ''}`}
                            onClick={() => { if (!isBusy) fileInputRef.current?.click(); }}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                        >
                            <div className="add-source-dropzone-content">
                                <p>📁</p>
                                <p>拖放文件到此处或点击选择文件</p>
                                <p>当前仅支持 PDF、DOC/DOCX、TXT、Markdown</p>
                            </div>
                        </div>

                        <div className="add-source-buttons">
                            <button className="add-source-btn" onClick={() => fileInputRef.current?.click()} disabled={isBusy}>
                                <span className="add-source-btn-icon">⬆</span>
                                {isUploading ? '上传中...' : '上传文件'}
                            </button>
                        </div>
                    </>
                )}

                {activeTab === 'web' && (
                    <div className="add-source-form">
                        <div className="add-source-search">
                            <span>🔗</span>
                            <input
                                placeholder="粘贴网站链接"
                                value={webUrl}
                                onChange={(event) => setWebUrl(event.target.value)}
                            />
                        </div>
                        <div className="add-source-search">
                            <span>🏷️</span>
                            <input
                                placeholder="可选：自定义标题"
                                value={webTitle}
                                onChange={(event) => setWebTitle(event.target.value)}
                            />
                        </div>
                        <div className="add-source-buttons">
                            <button className="add-source-btn add-source-btn-primary" onClick={handleCreateSource} disabled={isBusy}>
                                <span className="add-source-btn-icon">🌐</span>
                                {isSubmitting ? '添加中...' : '添加网站'}
                            </button>
                        </div>
                    </div>
                )}

                {activeTab === 'text' && (
                    <div className="add-source-form">
                        <div className="add-source-search">
                            <span>🏷️</span>
                            <input
                                placeholder="标题"
                                value={textTitle}
                                onChange={(event) => setTextTitle(event.target.value)}
                            />
                        </div>
                        <textarea
                            className="add-source-textarea"
                            placeholder="粘贴你要保存的文字内容"
                            value={textContent}
                            onChange={(event) => setTextContent(event.target.value)}
                        />
                        <div className="add-source-buttons">
                            <button className="add-source-btn add-source-btn-primary" onClick={handleCreateSource} disabled={isBusy}>
                                <span className="add-source-btn-icon">📋</span>
                                {isSubmitting ? '保存中...' : '保存文字来源'}
                            </button>
                        </div>
                    </div>
                )}

                {error && <p className="add-source-subtitle add-source-error">{error}</p>}

                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.doc,.docx,.txt,.md,text/plain,text/markdown,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    style={{ display: 'none' }}
                    onChange={(event) => {
                        handleFilesUpload(Array.from(event.target.files));
                        event.target.value = '';
                    }}
                />
            </div>
        </div>
    );
}
