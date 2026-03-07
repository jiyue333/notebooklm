import { useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import './AddSourceModal.css';

export default function AddSourceModal({ notebookId, onClose, onImported }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState('');
    const fileInputRef = useRef(null);

    const handleFilesUpload = async (files) => {
        if (!files?.length) return;

        try {
            setIsUploading(true);
            setError('');
            const detail = await appApi.sources.uploadFiles({ notebookId, files });
            onImported?.(detail);
            onClose();
        } catch (err) {
            setError(err.message || '上传来源失败');
        } finally {
            setIsUploading(false);
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
        <div className="add-source-overlay" onClick={onClose}>
            <div className="add-source-modal animate-scale-in" onClick={(event) => event.stopPropagation()}>
                <button className="add-source-close" onClick={onClose}>✕</button>

                <h2 className="add-source-title">添加来源</h2>
                <p className="add-source-subtitle">上传文件或搜索网络来源</p>

                <div className="add-source-search">
                    <span>🔍</span>
                    <input
                        placeholder="搜索或粘贴链接"
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                    />
                </div>

                <div className="add-source-tags">
                    <button className="add-source-tag active">🌐 Web ▾</button>
                    <button className="add-source-tag">🔄 Deep Research ▾</button>
                </div>

                <div
                    className={`add-source-dropzone ${isDragging ? 'dragging' : ''}`}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                >
                    <div className="add-source-dropzone-content">
                        <p>📁</p>
                        <p>拖放文件到此处</p>
                        <p>支持 PDF、图片、文档、音频等</p>
                    </div>
                </div>
                {error && <p className="add-source-subtitle">{error}</p>}

                <div className="add-source-buttons">
                    <button className="add-source-btn" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
                        <span className="add-source-btn-icon">⬆</span>
                        {isUploading ? '上传中...' : '上传文件'}
                    </button>
                    <button className="add-source-btn">
                        <span className="add-source-btn-icon">🌐</span>
                        网站
                    </button>
                    <button className="add-source-btn">
                        <span className="add-source-btn-icon">☁️</span>
                        云端硬盘
                    </button>
                    <button className="add-source-btn">
                        <span className="add-source-btn-icon">📋</span>
                        复制的文字
                    </button>
                </div>

                <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    style={{ display: 'none' }}
                    onChange={(event) => {
                        handleFilesUpload(Array.from(event.target.files));
                    }}
                />
            </div>
        </div>
    );
}
