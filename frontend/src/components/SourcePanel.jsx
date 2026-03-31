import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { appApi } from '../services/appApi';
import './SourcePanel.css';

const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));
const SEARCH_POLL_INTERVAL_MS = 1500;
const TERMINAL_SEARCH_STATUSES = new Set([
    'completed',
    'partial',
    'failed',
    'expired',
    'timeout',
    'timed_out',
    'cancelled',
    'canceled',
]);
const SEARCH_MODE_LABELS = {
    fast: 'Fast Research',
    auto: 'Auto Research',
    deep: 'Deep Research',
};
const SUMMARY_PREVIEW_LIMIT = 2;
const getSearchPollAttempts = (mode) => {
    if (mode === 'deep') return 1200;
    if (mode === 'auto') return 960;
    return 720;
};
const getSearchTimeoutMs = (mode) => {
    if (mode === 'deep') return 1_800_000;
    if (mode === 'auto') return 1_200_000;
    return 900_000;
};
const normalizeCardText = (value) => {
    const cleaned = Array.from(String(value || ''))
        .map((char) => {
            const code = char.charCodeAt(0);
            return (code <= 31 || code === 127 || code === 0xFFFD) ? ' ' : char;
        })
        .join('');
    return cleaned
        .replace(/[\u200B-\u200D\uFEFF]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
};
const truncateCardText = (value, maxLength) => {
    const normalized = normalizeCardText(value);
    if (!normalized) return '';
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, maxLength).trimEnd()}…`;
};
const stripReasonText = (value) => {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const normalized = raw
        .replace(/推荐理由\s*[:：]\s*/gi, ' ')
        .replace(/why\s*selected\s*[:：]\s*/gi, ' ')
        .replace(/核心内容\s*[:：]\s*/gi, ' ')
        .replace(/\n+/g, ' ');
    const splitByReason = normalized.split(/(?:推荐理由|why\s*selected)/i);
    return String(splitByReason[0] || normalized).trim();
};
const dedupeStrings = (values = []) => {
    const seen = new Set();
    const result = [];
    values.forEach((value) => {
        const normalized = String(value || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        result.push(normalized);
    });
    return result;
};
const normalizeSearchStatus = (status) => String(status || '').toLowerCase();
const isTerminalSearchStatus = (status) => TERMINAL_SEARCH_STATUSES.has(normalizeSearchStatus(status));
const getModeLabel = (mode) => SEARCH_MODE_LABELS[mode] || SEARCH_MODE_LABELS.auto;

const Ic = {
    link: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z" /></svg>,
    add: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z" /></svg>,
    search: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" /></svg>,
    web: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95c-.32-1.25-.78-2.45-1.38-3.56 1.84.63 3.37 1.91 4.33 3.56zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56-1.84-.63-3.37-1.91-4.33-3.56zm2.95-8H5.08c.96-1.65 2.49-2.93 4.33-3.56C8.81 5.55 8.35 6.75 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95c-.96 1.65-2.49 2.93-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z" /></svg>,
    fastResearch: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" /><circle cx="12" cy="12" r="2" /></svg>,
    deepResearch: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 4.86 5.36.78-3.88 3.78.92 5.34L12 14.24l-4.8 2.52.92-5.34L4.24 7.64l5.36-.78L12 2zm0 5.4-1.01 2.04-2.25.33 1.63 1.59-.38 2.24L12 12.53l2.01 1.07-.38-2.24 1.63-1.59-2.25-.33L12 7.4z" /></svg>,
    send: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>,
    refresh: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z" /></svg>,
    openLink: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" /></svg>,
    check: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.41 1.41L9 19 21 7l-1.41-1.41z" /></svg>,
    chevronDown: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 10l5 5 5-5z" /></svg>,
    spark: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M11 2 8.5 8.5 2 11l6.5 2.5L11 20l2.5-6.5L20 11l-6.5-2.5L11 2zm7 10 1.5 3L23 16.5 19.5 18 18 21.5 16.5 18 13 16.5 16.5 15 18 12z" /></svg>,
    thumbUp: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2 21h4V9H2v12zM22 10.5c0-.83-.67-1.5-1.5-1.5h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L13.66 2 7.59 8.07C7.22 8.44 7 8.95 7 9.5V19c0 1.1.9 2 2 2h8c.82 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1.5z" /></svg>,
    thumbDown: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M22 3h-4v12h4V3zM2 13.5C2 14.33 2.67 15 3.5 15h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L10.34 22l6.07-6.07c.37-.37.59-.88.59-1.43V5c0-1.1-.9-2-2-2H7c-.82 0-1.54.5-1.84 1.22L2.14 11.27c-.09.23-.14.47-.14.73v1.5z" /></svg>,
    trash: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zm3.46-7.12 1.41-1.41L12 11.59l1.12-1.12 1.41 1.41L13.41 13l1.12 1.12-1.41 1.41L12 14.41l-1.12 1.12-1.41-1.41L10.59 13l-1.13-1.12zM15.5 4l-1-1h-5l-1 1H5v2h14V4z" /></svg>,
    view: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 6a9.77 9.77 0 0 1 8.82 5.5A9.77 9.77 0 0 1 12 17a9.77 9.77 0 0 1-8.82-5.5A9.77 9.77 0 0 1 12 6Zm0-2C6.5 4 1.73 7.11 0 12c1.73 4.89 6.5 8 12 8s10.27-3.11 12-8c-1.73-4.89-6.5-8-12-8Zm0 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6z" /></svg>,
    collapseRight: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 4h18v16H3V4zm9 0v12h7V6h-7zm-1 8-4-4 4-4v8z" /></svg>,
};

export default function SourcePanel({
    notebookId,
    onAddSource,
    onCollapse,
    onDetailViewChange,
    onCollapsePanel,
    onSourcesImported,
    pendingSearchRequest,
    onSearchHandled,
}) {
    const [view, setView] = useState('default');
    const [isSearching, setIsSearching] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    const [isSearchLocked, setIsSearchLocked] = useState(false);
    const [searchInputValue, setSearchInputValue] = useState('');
    const [activeSearchQuery, setActiveSearchQuery] = useState('');
    const [searchViewState, setSearchViewState] = useState('idle');
    const [sources, setSources] = useState([]);
    const [searchSessionId, setSearchSessionId] = useState(null);
    const [searchModeLabel, setSearchModeLabel] = useState('Auto Research');
    const [searchStatus, setSearchStatus] = useState('idle');
    const [error, setError] = useState('');
    const [mode, setMode] = useState('auto');
    const [showModeDropdown, setShowModeDropdown] = useState(false);
    const [showDetailedResults, setShowDetailedResults] = useState(false);
    const modeDropRef = useRef(null);
    const searchLockRef = useRef(false);
    const importLockRef = useRef(false);
    const pollTokenRef = useRef(0);

    const isBusy = isSearching || isImporting || isSearchLocked;
    const allSelected = sources.length > 0 && sources.every((source) => source.selected);
    const selectedCount = sources.filter((source) => source.selected).length;
    const sortedSources = useMemo(() => [...sources].sort((left, right) => (right.finalScore || 0) - (left.finalScore || 0)), [sources]);
    const summarySources = sortedSources.slice(0, Math.min(sortedSources.length, SUMMARY_PREVIEW_LIMIT));
    const normalizedSearchStatus = normalizeSearchStatus(searchStatus);
    const isSearchingState = isSearching || normalizedSearchStatus === 'queued' || normalizedSearchStatus === 'running';
    const isCompletedState = normalizedSearchStatus === 'completed' || normalizedSearchStatus === 'partial';
    const isCompactSearchBar = view === 'results' && !isSearchingState;

    const modeOptions = useMemo(() => ([
        { id: 'fast', label: 'Fast Research', icon: Ic.fastResearch, desc: '更快' },
        { id: 'auto', label: 'Auto Research', icon: Ic.web, desc: '平衡' },
        { id: 'deep', label: 'Deep Research', icon: Ic.deepResearch, desc: '更全面' },
    ]), []);
    const currentMode = modeOptions.find((item) => item.id === mode) || modeOptions[1];

    const syncSources = useCallback((items, preserveSelection = true) => {
        setSources((prev) => (items || []).map((source) => ({
            ...source,
            selected: preserveSelection
                ? prev.find((item) => item.id === source.id)?.selected ?? true
                : true,
        })));
    }, []);

    const applySearchPayload = useCallback((payload, preserveSelection = true) => {
        const normalizedStatus = normalizeSearchStatus(payload.status || 'completed');
        setSearchSessionId(payload.searchSessionId || null);
        setSearchModeLabel(payload.modeLabel || 'Auto Research');
        setSearchStatus(normalizedStatus);
        syncSources(payload.items || [], preserveSelection);
        if (normalizedStatus === 'completed' || normalizedStatus === 'partial') {
            setError('');
        }
    }, [syncSources]);

    useEffect(() => {
        const handler = (event) => {
            if (modeDropRef.current && !modeDropRef.current.contains(event.target)) {
                setShowModeDropdown(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    useEffect(() => {
        pollTokenRef.current += 1;
        setView('default');
        setSearchInputValue('');
        setActiveSearchQuery('');
        setSearchViewState('idle');
        setSources([]);
        setSearchSessionId(null);
        setSearchModeLabel('Auto Research');
        setSearchStatus('idle');
        setShowDetailedResults(false);
        setError('');
    }, [notebookId]);

    useEffect(() => () => {
        pollTokenRef.current += 1;
        searchLockRef.current = false;
        importLockRef.current = false;
    }, []);

    useEffect(() => {
        onDetailViewChange?.(showDetailedResults);
    }, [onDetailViewChange, showDetailedResults]);

    useEffect(() => {
        if (view === 'default') {
            setSearchViewState('idle');
            return;
        }
        if (isSearchingState) {
            setSearchViewState('searching');
            return;
        }
        if (isCompletedState) {
            setSearchViewState('completed');
            return;
        }
        if (['failed', 'expired', 'timeout', 'timed_out', 'cancelled', 'canceled'].includes(normalizedSearchStatus)) {
            setSearchViewState('error');
            return;
        }
        setSearchViewState('idle');
    }, [isCompletedState, isSearchingState, normalizedSearchStatus, view]);

    const pollSearchSession = useCallback(async (sessionId, activeToken, searchMode = 'auto') => {
        const maxAttempts = getSearchPollAttempts(searchMode);
        const timeoutMs = getSearchTimeoutMs(searchMode);
        const startTime = Date.now();
        let latest = null;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            if (activeToken !== pollTokenRef.current) {
                return null;
            }
            if ((Date.now() - startTime) > timeoutMs) {
                break;
            }
            if (attempt > 0) {
                await sleep(SEARCH_POLL_INTERVAL_MS);
                if (activeToken !== pollTokenRef.current) {
                    return null;
                }
            }
            let polled = null;
            try {
                polled = await appApi.sources.getSession({ notebookId, searchSessionId: sessionId });
            } catch (err) {
                if (activeToken !== pollTokenRef.current) {
                    return null;
                }
                latest = {
                    searchSessionId: sessionId,
                    mode: searchMode,
                    modeLabel: getModeLabel(searchMode),
                    status: 'failed',
                    execution: 'sync',
                    items: latest?.items || [],
                    message: err.message || '获取搜索会话状态失败，请重试',
                };
                applySearchPayload(latest, true);
                return latest;
            }
            if (activeToken !== pollTokenRef.current) {
                return null;
            }
            latest = polled;
            applySearchPayload(polled, true);
            if (isTerminalSearchStatus(polled.status)) {
                return polled;
            }
        }
        if (!latest) {
            latest = {
                searchSessionId: sessionId,
                mode: searchMode,
                modeLabel: getModeLabel(searchMode),
                status: 'timed_out',
                execution: 'sync',
                items: [],
                message: '搜索会话超时，请重试',
            };
            applySearchPayload(latest, true);
            return latest;
        }
        if (!isTerminalSearchStatus(latest.status)) {
            const timedOutPayload = {
                ...latest,
                status: 'timed_out',
                execution: 'sync',
                message: '搜索会话超时，请重试或切换模式',
            };
            applySearchPayload(timedOutPayload, true);
            return timedOutPayload;
        }
        return latest;
    }, [applySearchPayload, notebookId]);

    const handleSearch = useCallback(async ({ queryOverride, modeOverride } = {}) => {
        const normalizedQuery = (queryOverride ?? searchInputValue).trim();
        const nextMode = modeOverride ?? mode;
        if (!normalizedQuery || searchLockRef.current || importLockRef.current) {
            return;
        }

        pollTokenRef.current += 1;
        const activeToken = pollTokenRef.current;
        searchLockRef.current = true;
        setIsSearchLocked(true);
        setError('');
        setIsSearching(true);
        setView('results');
        setSearchViewState('searching');
        setSearchStatus('queued');
        setShowDetailedResults(false);
        setShowModeDropdown(false);
        setMode(nextMode);
        setActiveSearchQuery(normalizedQuery);
        setSearchInputValue('');
        try {
            const result = await appApi.sources.search({
                notebookId,
                query: normalizedQuery,
                mode: nextMode,
            });
            if (activeToken !== pollTokenRef.current) {
                return;
            }
            applySearchPayload(result, false);
            if (result.execution === 'async' && result.searchSessionId) {
                const finalPayload = await pollSearchSession(
                    result.searchSessionId,
                    activeToken,
                    result.mode || nextMode,
                );
                if (activeToken !== pollTokenRef.current || !finalPayload) {
                    return;
                }
                const finalStatus = normalizeSearchStatus(finalPayload.status);
                const hasAnyResult = Array.isArray(finalPayload.items) && finalPayload.items.length > 0;
                if (['failed', 'expired', 'timeout', 'timed_out', 'cancelled', 'canceled'].includes(finalStatus)) {
                    if (hasAnyResult) {
                        setError('');
                        setSearchViewState('completed');
                    } else {
                        setError(finalPayload.message || '搜索未完成，请重试');
                        setSearchViewState('error');
                    }
                } else if (['completed', 'partial'].includes(finalStatus)) {
                    setSearchViewState('completed');
                }
            }
        } catch (err) {
            if (activeToken !== pollTokenRef.current) {
                return;
            }
            setError(err.message || '搜索来源失败');
            setSearchStatus('failed');
            setSearchViewState('error');
        } finally {
            if (activeToken === pollTokenRef.current) {
                searchLockRef.current = false;
                setIsSearching(false);
                setIsSearchLocked(false);
            }
        }
    }, [applySearchPayload, importLockRef, mode, notebookId, pollSearchSession, searchInputValue]);

    useEffect(() => {
        if (!pendingSearchRequest?.requestId) {
            return;
        }
        const { query, mode: requestedMode, requestId } = pendingSearchRequest;
        void handleSearch({
            queryOverride: query,
            modeOverride: requestedMode || 'fast',
        }).finally(() => {
            onSearchHandled?.(requestId);
        });
    }, [handleSearch, onSearchHandled, pendingSearchRequest]);

    const toggleSource = (id) => {
        setSources((prev) => prev.map((source) => (
            source.id === id ? { ...source, selected: !source.selected } : source
        )));
    };

    const toggleAll = () => {
        setSources((prev) => prev.map((source) => ({ ...source, selected: !allSelected })));
    };

    const handleImport = async () => {
        if (importLockRef.current || searchLockRef.current || selectedCount === 0) {
            return;
        }
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
            setSearchViewState('idle');
            setSearchStatus('idle');
            setShowDetailedResults(false);
            setSearchInputValue('');
            setActiveSearchQuery('');
            setSources([]);
            setSearchSessionId(null);
            onCollapse?.();
        } catch (err) {
            setError(err.message || '导入来源失败');
        } finally {
            importLockRef.current = false;
            setIsImporting(false);
        }
    };

    const buildFaviconCandidates = (source) => {
        const direct = String(source?.faviconUrl || '').trim();
        const candidates = [];
        if (direct) candidates.push(direct);

        const tryExtractHost = (raw) => {
            const normalized = String(raw || '').trim();
            if (!normalized) return '';
            try {
                const parsed = new URL(normalized.startsWith('http') ? normalized : `https://${normalized}`);
                return parsed.hostname || '';
            } catch {
                return '';
            }
        };

        const host = tryExtractHost(source?.domain) || tryExtractHost(source?.url);
        if (host) {
            candidates.push(`https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`);
            candidates.push(`https://icons.duckduckgo.com/ip3/${host}.ico`);
            candidates.push(`https://${host}/favicon.ico`);
        }
        return dedupeStrings(candidates);
    };
    const advanceFaviconCandidate = (event, candidates = []) => {
        const img = event.currentTarget;
        const wrap = img.closest('.sp-summary-favicon-wrap, .sp-result-favicon-wrap');
        const currentIndex = Number(img.dataset.faviconIndex || '0');
        const nextIndex = Number.isFinite(currentIndex) ? currentIndex + 1 : 1;
        if (nextIndex < candidates.length) {
            img.dataset.faviconIndex = String(nextIndex);
            img.src = candidates[nextIndex];
            return;
        }
        wrap?.classList.add('is-failed');
        img.remove();
    };
    const buildSourceCoreContent = (source, maxLength = 150) => {
        const rawContent = stripReasonText(source.description)
            || stripReasonText(Array.isArray(source.highlights) ? source.highlights[0] : '')
            || '该来源可补充当前研究主题的关键信息';
        return truncateCardText(rawContent, maxLength);
    };
    const handleClearSearchResult = () => {
        if (isBusy) return;
        pollTokenRef.current += 1;
        searchLockRef.current = false;
        setIsSearchLocked(false);
        setIsSearching(false);
        setView('default');
        setSearchViewState('idle');
        setSearchStatus('idle');
        setSearchSessionId(null);
        setSources([]);
        setShowDetailedResults(false);
        setSearchInputValue('');
        setActiveSearchQuery('');
        setError('');
    };

    const renderSearchBar = () => (
        <div className={`sp-search-area ${isCompactSearchBar ? 'compact' : ''}`}>
            <div className={`sp-search-box ${isCompactSearchBar ? 'compact' : ''}`}>
                {isCompactSearchBar ? (
                    <div className="sp-search-compact-row">
                        <span className="sp-search-icon">{Ic.search}</span>
                        <span className="sp-search-compact-query">{activeSearchQuery || '当前主题'}</span>
                        <button
                            type="button"
                            className="sp-search-reset-btn"
                            onClick={handleClearSearchResult}
                            disabled={isBusy}
                        >
                            清除
                        </button>
                    </div>
                ) : (
                    <>
                        <div className="sp-search-input-row">
                            <span className="sp-search-icon">{Ic.search}</span>
                            <textarea
                                className="sp-search-input"
                                placeholder="在网络中搜索新来源"
                                value={searchInputValue}
                                disabled={isSearchLocked}
                                onChange={(event) => setSearchInputValue(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter' && !event.shiftKey && !isSearchLocked) {
                                        event.preventDefault();
                                        void handleSearch();
                                    }
                                }}
                                rows={1}
                            />
                        </div>
                        <div className="sp-search-actions">
                            <div className="sp-mode-selector">
                                <div className="sp-mode-drop-wrapper" ref={modeDropRef}>
                                    <button
                                        type="button"
                                        className="sp-mode-btn active"
                                        onClick={() => setShowModeDropdown((current) => !current)}
                                        disabled={isSearchLocked}
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
                                                    type="button"
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
                                                    {mode === option.id ? <span className="sp-mode-option-check">{Ic.check}</span> : null}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </div>
                            <button type="button" className="sp-submit-btn" onClick={() => void handleSearch()} disabled={isBusy || !searchInputValue.trim()}>
                                {searchViewState === 'searching' ? <span className="sp-spinner" /> : Ic.send}
                            </button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );

    const renderSummaryResults = () => (
        <div className="sp-results-shell">
            {!showDetailedResults ? (
                <>
                    {isSearchingState ? (
                        <div className="sp-running-card">
                            <span className="sp-running-icon">{Ic.refresh}</span>
                            <span>正在研究...</span>
                        </div>
                    ) : isCompletedState && sortedSources.length > 0 ? (
                        <div className="sp-summary-card">
                            <div className="sp-summary-header">
                                <div className="sp-summary-title-wrap">
                                    <span className="sp-summary-icon">{Ic.spark}</span>
                                    <strong className="sp-summary-title-text">{searchModeLabel} 已完成</strong>
                                </div>
                                <button type="button" className="sp-summary-view-btn" onClick={() => setShowDetailedResults(true)}>
                                    <span>{Ic.view}</span>
                                    <span>查看详情</span>
                                </button>
                            </div>
                            <div className="sp-summary-list">
                                {summarySources.map((source, index) => {
                                    const faviconCandidates = buildFaviconCandidates(source);
                                    const favicon = faviconCandidates[0] || '';
                                    const sourceKey = source.id || source.url || `${source.title || 'source'}-${index + 1}`;
                                    return (
                                        <button
                                            key={sourceKey}
                                            type="button"
                                            className="sp-summary-item"
                                            aria-label={source.title}
                                            onClick={() => setShowDetailedResults(true)}
                                        >
                                            <span className={`sp-summary-favicon-wrap ${favicon ? 'has-image' : 'no-image'}`}>
                                                {favicon ? (
                                                    <img
                                                        className="sp-summary-favicon"
                                                        src={favicon}
                                                        alt=""
                                                        loading="lazy"
                                                        data-favicon-index="0"
                                                        onError={(event) => {
                                                            advanceFaviconCandidate(event, faviconCandidates);
                                                        }}
                                                    />
                                                ) : null}
                                                <span className="sp-summary-favicon-fallback" aria-hidden>{Ic.link}</span>
                                            </span>
                                            <span className="sp-summary-item-text">
                                                <span className="sp-summary-item-title">{source.title}</span>
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                            {sortedSources.length > summarySources.length ? (
                                <button type="button" className="sp-summary-more-line" onClick={() => setShowDetailedResults(true)}>
                                    另外 {sortedSources.length - summarySources.length} 个来源
                                </button>
                            ) : null}
                            <div className="sp-summary-actions">
                                <div className="sp-summary-action-group">
                                    <button type="button" className="sp-summary-delete-btn" onClick={handleClearSearchResult} disabled={isBusy}>
                                        {Ic.trash}
                                        <span>删除</span>
                                    </button>
                                    <button type="button" className="sp-import-btn" onClick={handleImport} disabled={selectedCount === 0 || isBusy}>
                                        {isImporting ? '导入中...' : '导入'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="sp-feedback-empty sp-feedback-empty-card">
                            {searchStatus === 'failed' ? '搜索失败，请重试' : '没有找到相关来源'}
                        </div>
                    )}
                </>
            ) : null}
        </div>
    );

    const renderDetailedResults = () => (
        <div className="sp-detail-shell">
            <div className="sp-detail-header">
                <div className="sp-results-query">
                    <span className="sp-results-query-icon">{Ic.refresh}</span>
                    <strong>{activeSearchQuery || '当前主题'}</strong>
                </div>
                <button type="button" className="sp-more-btn" onClick={() => setShowDetailedResults(false)}>
                    返回
                </button>
            </div>
            <div className="sp-results-card sp-results-card-detail">
                <div className="sp-results-header">
                    <button type="button" className="sp-results-select-all" onClick={toggleAll} disabled={isBusy}>
                        <span>选择所有来源</span>
                    </button>
                    <button type="button" className={`sp-checkbox ${allSelected ? 'checked' : ''}`} onClick={toggleAll} disabled={isBusy}>
                        {allSelected ? Ic.check : null}
                    </button>
                </div>

                <div className="sp-results-list">
                    {sortedSources.length > 0 ? sortedSources.map((source, index) => {
                        const faviconCandidates = buildFaviconCandidates(source);
                        const favicon = faviconCandidates[0] || '';
                        const sourceKey = source.id || source.url || `${source.title || 'source'}-${index + 1}`;
                        return (
                            <div key={sourceKey} className="sp-result-row">
                                <span className={`sp-result-favicon-wrap ${favicon ? 'has-image' : 'no-image'}`}>
                                    {favicon ? (
                                        <img
                                            className="sp-result-favicon"
                                            src={favicon}
                                            alt=""
                                            loading="lazy"
                                            data-favicon-index="0"
                                            onError={(event) => {
                                                advanceFaviconCandidate(event, faviconCandidates);
                                            }}
                                        />
                                    ) : null}
                                    <span className="sp-result-favicon-fallback" aria-hidden>{Ic.link}</span>
                                </span>
                                <div className="sp-result-content">
                                    <div className="sp-result-title-row">
                                        <span className="sp-result-title">{source.title}</span>
                                    </div>
                                    <div className="sp-result-field">
                                        <span className="sp-result-field-label">核心内容</span>
                                        <span className="sp-result-desc">{buildSourceCoreContent(source, 150)}</span>
                                    </div>
                                </div>
                                <button
                                    type="button"
                                    className="sp-result-link"
                                    title="打开原网页"
                                    onClick={() => window.open(source.url, '_blank', 'noopener,noreferrer')}
                                    disabled={isBusy}
                                >
                                    {Ic.openLink}
                                </button>
                                <button type="button" className={`sp-checkbox ${source.selected ? 'checked' : ''}`} onClick={() => toggleSource(source.id)} disabled={isBusy}>
                                    {source.selected ? Ic.check : null}
                                </button>
                            </div>
                        );
                    }) : (
                        <div className="sp-feedback-empty sp-feedback-empty-card">
                            没有找到相关来源
                        </div>
                    )}
                </div>
            </div>
            <div className="sp-results-footer">
                <span className="sp-results-count">已选择 {selectedCount} 个来源</span>
                <button type="button" className="sp-import-btn" onClick={handleImport} disabled={selectedCount === 0 || isBusy}>
                    {isImporting ? '导入中...' : '导入'}
                </button>
            </div>
        </div>
    );

    return (
        <>
            <div className="nb-panel-header sp-panel-header">
                <span className="nb-panel-icon">{Ic.link}</span>
                <span className="nb-panel-title">来源</span>
                {onCollapsePanel ? (
                    <button type="button" className="nb-panel-collapse-icon" onClick={onCollapsePanel} title="收起右栏">
                        {Ic.collapseRight}
                    </button>
                ) : null}
            </div>
            <div className={`nb-panel-body sp-panel-body-results ${showDetailedResults ? 'detail-mode' : ''}`}>
                {showDetailedResults ? (
                    renderDetailedResults()
                ) : (
                    <>
                        <button type="button" className="sp-add-source-btn" onClick={onAddSource} disabled={isImporting}>
                            <span className="sp-add-icon">{Ic.add}</span>
                            <span>添加来源</span>
                        </button>
                        {renderSearchBar()}
                        {error ? <p className="sp-feedback-error">{error}</p> : null}
                        {view === 'results' ? renderSummaryResults() : null}
                    </>
                )}
            </div>
        </>
    );
}
