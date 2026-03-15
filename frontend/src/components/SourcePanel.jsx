import { useEffect, useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import './SourcePanel.css';

/* Tidyflux-style filled SVG icons */
const Ic = {
    link: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z" /></svg>,
    add: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg>,
    search: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" /></svg>,
    web: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95c-.32-1.25-.78-2.45-1.38-3.56 1.84.63 3.37 1.91 4.33 3.56zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56-1.84-.63-3.37-1.91-4.33-3.56zm2.95-8H5.08c.96-1.65 2.49-2.93 4.33-3.56C8.81 5.55 8.35 6.75 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95c-.96 1.65-2.49 2.93-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z" /></svg>,
    fastResearch: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" /><circle cx="12" cy="12" r="2" /></svg>,
    deepResearch: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" /></svg>,
    send: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>,
    refresh: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" /></svg>,
    openLink: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" /></svg>,
    back: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" /></svg>,
    check: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.41 1.41L9 19 21 7l-1.41-1.41z" /></svg>,
    chevronDown: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>,
};

export default function SourcePanel({
    notebookId,
    searchQuery,
    setSearchQuery,
    onAddSource,
    onExpand,
    onCollapse,
    onSourcesImported,
}) {
    const [view, setView] = useState('default');
    const [isSearching, setIsSearching] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [sources, setSources] = useState([]);
    const [searchSessionId, setSearchSessionId] = useState(null);
    const [searchModeLabel, setSearchModeLabel] = useState('Auto Research');
    const [error, setError] = useState('');

    const [mode, setMode] = useState('auto');
    const [showModeDropdown, setShowModeDropdown] = useState(false);
    const modeDropRef = useRef(null);
    const searchLockRef = useRef(false);
    const importLockRef = useRef(false);

    const selectedCount = sources.filter((source) => source.selected).length;
    const isBusy = isSearching || isImporting;

    useEffect(() => {
        const handler = (event) => {
            if (modeDropRef.current && !modeDropRef.current.contains(event.target)) setShowModeDropdown(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    useEffect(() => {
        setView('default');
        setSources([]);
        setSearchSessionId(null);
        setSearchModeLabel('Auto Research');
        setError('');
    }, [notebookId]);

    const handleSearch = async () => {
        if (!searchQuery.trim() || searchLockRef.current || importLockRef.current) return;
        searchLockRef.current = true;
        setError('');
        setIsSearching(true);

        try {
            const result = await appApi.sources.search({
                notebookId,
                query: searchQuery,
                mode,
            });
            setSearchSessionId(result.searchSessionId || null);
            setSearchModeLabel(result.modeLabel || 'Auto Research');
            setSources((result.items || []).map((source) => ({
                ...source,
                selected: true,
            })));
            setView('results');
        } catch (err) {
            setError(err.message || '搜索来源失败');
        } finally {
            searchLockRef.current = false;
            setIsSearching(false);
        }
    };

    const handleSearchKeyDown = (event) => {
        if (event.key === 'Enter') handleSearch();
    };

    const toggleSource = (id) => {
        setSources((prev) => prev.map((source) => (
            source.id === id ? { ...source, selected: !source.selected } : source
        )));
    };

    const toggleAll = () => {
        const allSelected = sources.every((source) => source.selected);
        setSources((prev) => prev.map((source) => ({ ...source, selected: !allSelected })));
    };

    const handleImport = async () => {
        if (importLockRef.current || searchLockRef.current || selectedCount === 0) return;
        try {
            importLockRef.current = true;
            setError('');
            setIsImporting(true);
            if (!searchSessionId) {
                throw new Error('缺少搜索会话，请重新搜索后再导入');
            }
            const detail = await appApi.sources.importSelected({
                notebookId,
                searchSessionId,
                searchResultIds: sources.filter((source) => source.selected).map((source) => source.id),
            });
            onSourcesImported?.(detail);
            setView('default');
            setSearchQuery('');
            setSearchSessionId(null);
            if (onCollapse) onCollapse();
        } catch (err) {
            setError(err.message || '导入来源失败');
        } finally {
            importLockRef.current = false;
            setIsImporting(false);
        }
    };

    const handleViewDiscover = () => {
        setView('discover');
        if (onExpand) onExpand();
    };

    const handleBackFromDiscover = () => {
        setView('results');
        if (onCollapse) onCollapse();
    };

    const modeOptions = [
        { id: 'fast', label: 'Fast Research', icon: Ic.fastResearch, desc: '低延迟返回候选结果' },
        { id: 'auto', label: 'Auto Research', icon: Ic.web, desc: '默认平衡模式，适合大多数搜索' },
        { id: 'deep', label: 'Deep Research', icon: Ic.deepResearch, desc: '更慢但更深入的来源发现' },
    ];
    const currentMode = modeOptions.find((item) => item.id === mode) || modeOptions[1];
    const buildSourceBadge = (source) => source.sourceTypeBadge || source.sourceName || '来源';
    const buildSourceSummary = (source) => source.whySelected || source.description || '已按当前研究任务筛选';
    const buildHighlight = (source) => (Array.isArray(source.highlights) && source.highlights[0]) || '';
    const buildImportLabel = (source) => {
        const mapping = {
            recommended: '推荐导入',
            optional: '可选',
            duplicate_risk: '重复风险',
        };
        return mapping[source.importSuggestion] || source.importSuggestion || '可选';
    };

    const renderSearchBar = () => (
        <div className="sp-search-area">
            <div className="sp-search-box">
                <span className="sp-search-icon">{Ic.search}</span>
                <input
                    className="sp-search-input"
                    placeholder="在网络中搜索新来源"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    onKeyDown={handleSearchKeyDown}
                />
            </div>
            <div className="sp-search-actions">
                <div className="sp-mode-selector">
                    <div className="sp-mode-drop-wrapper" ref={modeDropRef}>
                        <button
                            className="sp-mode-btn active"
                            onClick={() => {
                                setShowModeDropdown(!showModeDropdown);
                            }}
                        >
                            <span className="sp-mode-btn-icon">{currentMode.icon}</span>
                            <span>{currentMode.label}</span>
                            <span className="sp-mode-caret">{Ic.chevronDown}</span>
                        </button>
                        {showModeDropdown && (
                            <div className="sp-mode-dropdown">
                                {modeOptions.map((option) => (
                                    <button
                                        key={option.id}
                                        className={`sp-mode-option ${mode === option.id ? 'active' : ''}`}
                                        onClick={() => {
                                            setMode(option.id);
                                            setShowModeDropdown(false);
                                        }}
                                    >
                                        <span className="sp-mode-option-icon">{option.icon}</span>
                                        <div className="sp-mode-option-info">
                                            <span className="sp-mode-option-label">{option.label}</span>
                                            <span className="sp-mode-option-desc">{option.desc}</span>
                                        </div>
                                        {mode === option.id && <span className="sp-mode-option-check">{Ic.check}</span>}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
                <button className="sp-submit-btn" onClick={handleSearch} disabled={isBusy}>
                    {isSearching ? <span className="sp-spinner" /> : Ic.send}
                </button>
            </div>
        </div>
    );

    if (view === 'default') {
        return (
            <>
                <div className="nb-panel-header">
                    <span className="nb-panel-icon">{Ic.link}</span>
                    <span className="nb-panel-title">来源</span>
                </div>
                <div className="nb-panel-body sp-panel-body-results">
                    <button className="sp-add-source-btn" onClick={onAddSource} disabled={isImporting}>
                        <span className="sp-add-icon">{Ic.add}</span>
                        <span>添加来源</span>
                    </button>
                    {renderSearchBar()}
                    {isSearching && (
                        <div className="sp-searching">
                            <span className="sp-spinner" />
                            <span>正在搜索中...</span>
                        </div>
                    )}
                    {error && <p className="sp-feedback-error">{error}</p>}
                </div>
            </>
        );
    }

    if (view === 'results') {
        const previewSources = sources.slice(0, 3);
        const remainingCount = sources.length - 3;

        return (
            <>
                <div className="nb-panel-header">
                    <span className="nb-panel-icon">{Ic.link}</span>
                    <span className="nb-panel-title">来源</span>
                </div>
                <div className="nb-panel-body sp-panel-body-results">
                    <button className="sp-add-source-btn" onClick={onAddSource} disabled={isImporting}>
                        <span className="sp-add-icon">{Ic.add}</span>
                        <span>添加来源</span>
                    </button>
                    {renderSearchBar()}
                    {error && <p className="sp-feedback-error">{error}</p>}

                    <div className="sp-results-card">
                        <div className="sp-results-header">
                            <span className="sp-results-icon">{Ic.refresh}</span>
                            <span className="sp-results-title">{searchModeLabel} 已完成！</span>
                            <button className="sp-view-btn" onClick={handleViewDiscover} disabled={isImporting}>查看</button>
                        </div>
                        <div className="sp-results-list">
                            {previewSources.length > 0 ? previewSources.map((source) => (
                                <div key={source.id} className="sp-result-item">
                                    <span className="sp-result-badge">{buildSourceBadge(source)}</span>
                                    <div className="sp-result-info">
                                        <div className="sp-result-title-row">
                                            <span className="sp-result-title">{source.title}</span>
                                            {source.authorityBadge && (
                                                <span className="sp-result-chip">{source.authorityBadge}</span>
                                            )}
                                        </div>
                                        <span className="sp-result-desc">{buildSourceSummary(source)}</span>
                                        {buildHighlight(source) && (
                                            <span className="sp-result-highlight">{buildHighlight(source)}</span>
                                        )}
                                    </div>
                                </div>
                            )) : (
                                <div className="sp-feedback-empty">没有找到相关来源</div>
                            )}
                            {remainingCount > 0 && (
                                <div className="sp-result-more">
                                    <span className="sp-result-more-icon">{Ic.link}</span>
                                    <span>另外 {remainingCount} 个来源</span>
                                </div>
                            )}
                        </div>
                        <div className="sp-results-footer">
                            <button className="sp-delete-btn" onClick={() => setView('default')} disabled={isImporting}>删除</button>
                            <button className="sp-import-btn" onClick={handleImport} disabled={selectedCount === 0 || isBusy}>
                                {isImporting ? '导入中...' : '+ 导入'}
                            </button>
                        </div>
                    </div>
                </div>
            </>
        );
    }

    return (
        <>
            <div className="nb-panel-header">
                <span className="sp-breadcrumb">
                    <button className="sp-breadcrumb-link" onClick={handleBackFromDiscover}>
                        {Ic.back} 来源
                    </button>
                    <span className="sp-breadcrumb-sep">›</span>
                    <span className="sp-breadcrumb-current">来源发现</span>
                </span>
            </div>
            <div className="nb-panel-body sp-discover-body">
                <p className="sp-discover-summary">
                    这组候选已按当前研究任务做过覆盖式筛选，优先展示值得导入的来源、视角补位和解析可用性信号。
                </p>
                <div className="sp-discover-list">
                    <div className="sp-discover-header">
                        <span>选择所有来源</span>
                        <button className={`sp-checkbox ${sources.every((source) => source.selected) ? 'checked' : ''}`} onClick={toggleAll} disabled={isImporting}>
                            {sources.every((source) => source.selected) && Ic.check}
                        </button>
                    </div>
                    <div className="sp-discover-list-scroll">
                        {sources.map((source) => (
                            <div key={source.id} className="sp-discover-item">
                                <span className="sp-discover-item-icon">{buildSourceBadge(source)}</span>
                                <div className="sp-discover-item-info">
                                    <div className="sp-discover-item-title-row">
                                        <span className="sp-discover-item-title">{source.title}</span>
                                        {source.authorityBadge && (
                                            <span className="sp-result-chip">{source.authorityBadge}</span>
                                        )}
                                    </div>
                                    <div className="sp-discover-item-meta">
                                        {source.sourceName && <span>{source.sourceName}</span>}
                                        <span>{buildImportLabel(source)}</span>
                                    </div>
                                    <span className="sp-discover-item-desc">{buildSourceSummary(source)}</span>
                                    {buildHighlight(source) && (
                                        <span className="sp-discover-item-highlight">{buildHighlight(source)}</span>
                                    )}
                                </div>
                                <button className="sp-discover-link" title="打开链接" onClick={() => window.open(source.url, '_blank', 'noopener,noreferrer')} disabled={isImporting}>{Ic.openLink}</button>
                                <button className={`sp-checkbox ${source.selected ? 'checked' : ''}`} onClick={() => toggleSource(source.id)} disabled={isImporting}>
                                    {source.selected && Ic.check}
                                </button>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="sp-discover-footer">
                    <span className="sp-discover-count">已选择 {selectedCount} 个来源</span>
                    <button className="sp-import-btn" onClick={handleImport} disabled={selectedCount === 0 || isBusy}>
                        {isImporting ? '导入中...' : '导入'}
                    </button>
                </div>
                {error && <p className="sp-feedback-error">{error}</p>}
            </div>
        </>
    );
}
