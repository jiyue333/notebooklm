import { useState, useRef } from 'react';
import './AddSourceModal.css';

export default function AddSourceModal({ onClose }) {
    const [searchQuery, setSearchQuery] = useState('');
    const [isDragging, setIsDragging] = useState(false);
    const fileInputRef = useRef(null);

    const handleDragOver = (e) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        const files = Array.from(e.dataTransfer.files);
        console.log('Dropped files:', files);
    };

    return (
        <div className="add-source-overlay" onClick={onClose}>
            <div className="add-source-modal animate-scale-in" onClick={(e) => e.stopPropagation()}>
                <button className="add-source-close" onClick={onClose}>✕</button>

                <h2 className="add-source-title">添加来源</h2>
                <p className="add-source-subtitle">上传文件或搜索网络来源</p>

                {/* Search */}
                <div className="add-source-search">
                    <span>🔍</span>
                    <input
                        placeholder="搜索或粘贴链接"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>

                <div className="add-source-tags">
                    <button className="add-source-tag active">🌐 Web ▾</button>
                    <button className="add-source-tag">🔄 Deep Research ▾</button>
                </div>

                {/* Dropzone */}
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

                {/* Action buttons */}
                <div className="add-source-buttons">
                    <button className="add-source-btn" onClick={() => fileInputRef.current?.click()}>
                        <span className="add-source-btn-icon">⬆</span>
                        上传文件
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
                    onChange={(e) => {
                        const files = Array.from(e.target.files);
                        console.log('Selected files:', files);
                    }}
                />
            </div>
        </div>
    );
}
