import { memo, startTransition, useState, useCallback, useRef, useEffect, useMemo, useDeferredValue } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { appApi, clearStoredSession, isAuthError } from '../services/appApi';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import SettingsModal from '../components/SettingsModal';
import AddSourceModal from '../components/AddSourceModal';
import SourcePanel from '../components/SourcePanel';
import NoteModal from '../components/NoteModal';
import './NotebookPage.css';

/* ============================================
   Resizer Hook
   ============================================ */
function useResizer(direction, initialSize, minSize, maxSize, inverted = false) {
    const [size, setSize] = useState(initialSize);
    const sizeRef = useRef(initialSize);

    useEffect(() => {
        sizeRef.current = size;
    }, [size]);

    const onMouseDown = useCallback((e) => {
        e.preventDefault();
        const startPos = direction === 'horizontal' ? e.clientX : e.clientY;
        const startSize = sizeRef.current;
        document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (ev) => {
            const currentPos = direction === 'horizontal' ? ev.clientX : ev.clientY;
            const delta = inverted ? (startPos - currentPos) : (currentPos - startPos);
            setSize(Math.min(maxSize, Math.max(minSize, startSize + delta)));
        };
        const onMouseUp = () => {
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    }, [direction, minSize, maxSize, inverted]);

    return [size, onMouseDown, setSize];
}

/* ============================================
   Extract TOC from markdown
   ============================================ */
function extractToc(markdown) {
    if (!markdown) return [];
    const lines = markdown.split('\n');
    const toc = [];
    let inCode = false;
    let skippedFirst = false;
    lines.forEach(line => {
        if (line.trim().startsWith('```')) { inCode = !inCode; return; }
        if (inCode) return;
        const m = line.match(/^(#{1,4})\s+(.+)$/);
        if (m) {
            const level = m[1].length;
            const title = m[2].trim();
            if (level === 1 && !skippedFirst) { skippedFirst = true; return; }
            const id = title.toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g, '-').replace(/(^-|-$)/g, '');
            toc.push({ id, title, level });
        }
    });
    return toc;
}

/* ============================================
   Strip first h1 from markdown
   ============================================ */
function stripFirstH1(markdown) {
    if (!markdown) return '';
    const lines = markdown.split('\n');
    let found = false;
    const result = [];
    for (const line of lines) {
        if (!found && /^#\s+/.test(line)) { found = true; continue; }
        result.push(line);
    }
    return result.join('\n').replace(/^\n+/, '');
}

function areTocEntriesEqual(left = [], right = []) {
    if (left === right) return true;
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
        return false;
    }
    return left.every((entry, index) => (
        entry?.id === right[index]?.id
        && entry?.title === right[index]?.title
        && entry?.level === right[index]?.level
    ));
}

function isSameArticleSnapshot(current, next) {
    if (current === next) return true;
    if (!current || !next || current.id !== next.id) return false;
    return current.title === next.title
        && current.author === next.author
        && current.date === next.date
        && current.content === next.content
        && current.contentReady === next.contentReady
        && current.parseStatus === next.parseStatus
        && current.renderMode === next.renderMode
        && current.fileUrl === next.fileUrl
        && current.processingHint === next.processingHint
        && areTocEntriesEqual(current.toc, next.toc);
}

const createChatMessageId = () => `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const CHAT_ROUTE_LABELS = {
    CURRENT_ARTICLE: '当前文章',
    RELATED_ARTICLES: '相关文章',
    EVIDENCE_LOOKUP: '证据检索',
    GENERAL: '通用问题',
};

const ARTICLE_MARKDOWN_REMARK_PLUGINS = [remarkGfm];
const ARTICLE_MARKDOWN_REHYPE_PLUGINS = [rehypeRaw, rehypeSlug];

const MarkdownDocument = memo(function MarkdownDocument({ content, className }) {
    if (!content?.trim()) {
        return null;
    }

    return (
        <div className={className}>
            <ReactMarkdown
                remarkPlugins={ARTICLE_MARKDOWN_REMARK_PLUGINS}
                rehypePlugins={ARTICLE_MARKDOWN_REHYPE_PLUGINS}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
});

const ArticleContentPane = memo(function ArticleContentPane({
    articleId,
    articleTitle,
    articleFileUrl,
    articleProcessingHint,
    articleDisplayBlocked,
    articleRenderMode,
    renderedArticleContent,
    fontSize,
    pageWidth,
    showSummary,
    summaryLoading,
    summaryText,
    showTranslation,
    translationLoading,
    translationText,
    translationLanguage,
    translationError,
    setShowSummary,
    setShowTranslation,
}) {
    const deferredArticleContent = useDeferredValue(renderedArticleContent);

    return (
        <div
            className="nb-article-content"
            style={{ fontSize: `${fontSize}rem`, maxWidth: `${pageWidth}px` }}
            data-article-id={articleId}
        >
            {showSummary && (
                <div className="nb-summary-card">
                    <div className="nb-summary-header">
                        <span className="nb-summary-icon">{I.sparkle}</span>
                        <span className="nb-summary-label">摘要</span>
                        <button className="nb-icon-btn-sm" onClick={() => setShowSummary(false)}>{I.close}</button>
                    </div>
                    <div className="nb-summary-body">
                        {summaryLoading ? (
                            <>
                                {summaryText ? (
                                    <MarkdownDocument className="nb-summary-markdown" content={summaryText} />
                                ) : null}
                                <div className="nb-summary-loading"><span className="nb-spinner" /><span>正在生成摘要...</span></div>
                            </>
                        ) : (
                            <MarkdownDocument className="nb-summary-markdown" content={summaryText} />
                        )}
                    </div>
                </div>
            )}
            {showTranslation && (
                <div className="nb-summary-card nb-translation-card">
                    <div className="nb-summary-header">
                        <span className="nb-summary-icon">{I.translate}</span>
                        <span className="nb-summary-label">
                            {translationLoading ? '正在翻译...' : `译文${translationLanguage ? ` · ${translationLanguage}` : ''}`}
                        </span>
                        <button className="nb-icon-btn-sm" onClick={() => setShowTranslation(false)}>{I.close}</button>
                    </div>
                    <div className="nb-summary-body">
                        {translationLoading ? (
                            <div className="nb-summary-loading"><span className="nb-spinner" /><span>正在生成译文...</span></div>
                        ) : translationError ? (
                            <p>{translationError}</p>
                        ) : (
                            <p>当前内容已切换为译文视图。</p>
                        )}
                    </div>
                </div>
            )}
            {articleDisplayBlocked ? (
                <div className="nb-article-pending">
                    <div className="nb-article-pending-icon">{I.paper}</div>
                    <h3>正文准备中</h3>
                    <p>{articleProcessingHint || '来源已导入，正在处理正文，请稍后刷新。'}</p>
                </div>
            ) : showTranslation && translationText ? (
                <MarkdownDocument content={deferredArticleContent} />
            ) : articleRenderMode === 'pdf' ? (
                articleFileUrl ? (
                    <iframe
                        title={articleTitle}
                        src={articleFileUrl}
                        style={{
                            width: '100%',
                            minHeight: '72vh',
                            border: '1px solid rgba(148, 163, 184, 0.28)',
                            borderRadius: '18px',
                            background: '#fff',
                        }}
                    />
                ) : (
                    <div className="nb-empty-hint"><p>PDF 文件暂不可访问</p></div>
                )
            ) : (
                <MarkdownDocument content={deferredArticleContent} />
            )}
        </div>
    );
});

/* ============================================
   SVG Icons – Tidyflux filled style (currentColor)
   ============================================ */
const I = {
    back: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z" /></svg>,
    translate: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0014.07 6H17V4h-7V2H8v2H1v2h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z" /></svg>,
    summary: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    chat: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z" /><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z" /></svg>,
    more: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" /></svg>,
    addNote: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    edit: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    theme: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 8.69V4h-4.69L12 .69 8.69 4H4v4.69L.69 12 4 15.31V20h4.69L12 23.31 15.31 20H20v-4.69L23.31 12 20 8.69zM12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-10c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z" /></svg>,
    settings: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" /></svg>,
    close: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" /></svg>,
    send: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>,
    sparkle: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    note: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" /></svg>,
    toc: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z" /></svg>,
    font: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9.93 13.5h4.14L12 7.98 9.93 13.5zM20 2H4c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-4.05 16.5l-1.14-3H9.17l-1.12 3H5.96l5.11-13h1.86l5.11 13h-2.09z" /></svg>,
    deleteChat: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" /></svg>,
    // Source-type icons (rendered in theme color via CSS)
    arxiv: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    github: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" /></svg>,
    paper: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zM13 9V3.5L18.5 9H13z" /></svg>,
    research: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z" /></svg>,
    article: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" /></svg>,
};

/* Map article type → icon */
function getArticleIcon(type) {
    switch (type) {
        case 'github': return I.github;
        case 'paper': return I.paper;
        case 'research': return I.research;
        case 'article': return I.article;
        default: return I.paper;
    }
}

/* ============================================
   Notebook Page
   ============================================ */
export default function NotebookPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const { toggleTheme } = useTheme();
    const requestedArticleId = searchParams.get('articleId');

    const [currentUser, setCurrentUser] = useState(null);
    const [notebook, setNotebook] = useState(null);
    const [selectedArticle, setSelectedArticle] = useState(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [showSettings, setShowSettings] = useState(false);
    const [showAddSource, setShowAddSource] = useState(false);
    const [sourceExpanded, setSourceExpanded] = useState(false);
    const [showArticleMenu, setShowArticleMenu] = useState(false);
    const [isPageLoading, setIsPageLoading] = useState(true);
    const [pageError, setPageError] = useState('');
    const menuRef = useRef(null);

    // AI features
    const [showSummary, setShowSummary] = useState(false);
    const [summaryText, setSummaryText] = useState('');
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [showAiChat, setShowAiChat] = useState(false);
    const [chatMessages, setChatMessages] = useState([]);
    const [chatConversationId, setChatConversationId] = useState(null);
    const [chatInput, setChatInput] = useState('');
    const [isChatStreaming, setIsChatStreaming] = useState(false);
    const [showTranslation, setShowTranslation] = useState(false);
    const [translationText, setTranslationText] = useState('');
    const [translationLoading, setTranslationLoading] = useState(false);
    const [translationLanguage, setTranslationLanguage] = useState('');
    const [translationError, setTranslationError] = useState('');

    // Article settings
    const [fontSize, setFontSize] = useState(1.05);
    const [pageWidth, setPageWidth] = useState(720);

    // Notes state
    const [notes, setNotes] = useState([]);
    const [noteModalData, setNoteModalData] = useState(null); // null = closed, object = open

    // Layout resizers — same default for visual alignment, but independent dragging
    const [leftWidth, onLeftResize] = useResizer('horizontal', 300, 200, 450);
    const [rightWidth, onRightResize] = useResizer('horizontal', 360, 260, 560, true);
    const [leftTopH, onLeftSplit] = useResizer('vertical', 440, 120, 650);
    const [rightTopH, onRightSplit] = useResizer('vertical', 440, 120, 650);

    const redirectToLogin = useCallback(() => {
        clearStoredSession();
        navigate('/login', { replace: true });
    }, [navigate]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setShowArticleMenu(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const syncNotebookState = useCallback((detail) => {
        setNotebook(detail);
        setNotes(detail.notes || []);
        setSelectedArticle((prev) => {
            const nextSelected = detail.articles.find((article) => article.id === prev?.id)
                || detail.articles[0]
                || null;
            return isSameArticleSnapshot(prev, nextSelected) ? prev : nextSelected;
        });
    }, []);

    useEffect(() => {
        let isMounted = true;

        const loadNotebookPage = async () => {
            try {
                setIsPageLoading(true);
                setPageError('');
                const [user, detail] = await Promise.all([
                    appApi.auth.getCurrentUser(),
                    appApi.notebooks.getDetail(id),
                ]);
                if (!isMounted) return;
                setCurrentUser(user);
                syncNotebookState(detail);
            } catch (err) {
                if (!isMounted) return;
                if (isAuthError(err)) {
                    redirectToLogin();
                    return;
                }
                setPageError(err.message || '加载笔记本失败');
            } finally {
                if (isMounted) setIsPageLoading(false);
            }
        };

        loadNotebookPage();
        return () => {
            isMounted = false;
        };
    }, [id, redirectToLogin, syncNotebookState]);

    useEffect(() => {
        if (!notebook || !requestedArticleId) return;
        const requestedArticle = notebook.articles.find((article) => article.id === requestedArticleId);
        if (requestedArticle && requestedArticle.id !== selectedArticle?.id) {
            setSelectedArticle(requestedArticle);
        }
    }, [notebook, requestedArticleId, selectedArticle?.id]);

    // Reset AI features when switching articles
    useEffect(() => {
        setShowSummary(false);
        setSummaryText('');
        setSummaryLoading(false);
        setShowTranslation(false);
        setTranslationText('');
        setTranslationLoading(false);
        setTranslationLanguage('');
        setTranslationError('');
    }, [selectedArticle?.id]);

    useEffect(() => {
        if (!id || !selectedArticle || selectedArticle.contentReady || selectedArticle.parseStatus === 'failed') {
            return undefined;
        }

        let cancelled = false;
        let timeoutId = null;

        const pollArticleReady = async () => {
            try {
                const detail = await appApi.notebooks.getDetail(id);
                if (cancelled) return;
                syncNotebookState(detail);
            } catch (err) {
                if (cancelled) return;
                if (isAuthError(err)) {
                    redirectToLogin();
                    return;
                }
            }

            if (!cancelled) {
                timeoutId = window.setTimeout(pollArticleReady, 2000);
            }
        };

        timeoutId = window.setTimeout(pollArticleReady, 1200);
        return () => {
            cancelled = true;
            if (timeoutId) {
                window.clearTimeout(timeoutId);
            }
        };
    }, [
        id,
        redirectToLogin,
        selectedArticle?.contentReady,
        selectedArticle?.id,
        selectedArticle?.parseStatus,
        syncNotebookState,
    ]);

    const articleRenderMode = selectedArticle?.renderMode || 'markdown';
    const articleContentReady = selectedArticle?.contentReady ?? Boolean(selectedArticle?.content?.trim());
    const articleDisplayBlocked = Boolean(selectedArticle)
        && articleRenderMode === 'markdown'
        && !articleContentReady;
    const toc = useMemo(() => {
        if (showTranslation && translationText) {
            return extractToc(translationText);
        }
        if (!selectedArticle) return [];
        if (articleDisplayBlocked) return [];
        if (Array.isArray(selectedArticle.toc) && selectedArticle.toc.length > 0) {
            return selectedArticle.toc;
        }
        if (articleRenderMode === 'pdf') {
            return [];
        }
        return extractToc(selectedArticle.content);
    }, [selectedArticle, showTranslation, translationText, articleRenderMode, articleDisplayBlocked]);
    const strippedContent = useMemo(() => (
        selectedArticle && articleRenderMode === 'markdown' && !articleDisplayBlocked
            ? stripFirstH1(selectedArticle.content)
            : ''
    ), [selectedArticle, articleRenderMode, articleDisplayBlocked]);
    const renderedArticleContent = useMemo(() => (
        showTranslation && translationText ? stripFirstH1(translationText) : strippedContent
    ), [showTranslation, translationText, strippedContent]);

    // AI Summary
    const handleSummary = async () => {
        if (showSummary) { setShowSummary(false); return; }
        if (!notebook || !selectedArticle) return;
        setShowSummary(true);
        setSummaryLoading(true);
        setSummaryText('');
        try {
            const result = await appApi.ai.streamSummary({
                notebookId: notebook.id,
                articleId: selectedArticle.id,
                onToken: (token) => {
                    setSummaryText((prev) => `${prev}${token}`);
                },
            });
            setSummaryText(result.summary);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setSummaryText(err.message || '生成摘要失败');
        } finally {
            setSummaryLoading(false);
        }
    };

    const handleTranslate = async () => {
        if (showTranslation) {
            setShowTranslation(false);
            return;
        }
        if (!notebook || !selectedArticle) return;

        setShowTranslation(true);
        setTranslationLoading(true);
        setTranslationText('');
        setTranslationError('');

        try {
            const settings = await appApi.settings.get();
            const targetLanguage = settings.outputLanguage || '中文';
            setTranslationLanguage(targetLanguage);
            const result = await appApi.ai.translateArticle({
                notebookId: notebook.id,
                articleId: selectedArticle.id,
                targetLanguage,
            });
            setTranslationText(result.translatedContent || '');
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setTranslationError(err.message || '翻译失败');
        } finally {
            setTranslationLoading(false);
        }
    };

    const handleToggleChat = () => {
        setShowAiChat(!showAiChat);
        if (!showAiChat) setSourceExpanded(false);
    };

    const handleSendChat = async () => {
        if (!chatInput.trim() || !notebook || isChatStreaming) return;
        const prompt = chatInput.trim();
        const pendingAssistantId = createChatMessageId();
        setChatMessages((prev) => [
            ...prev,
            { id: createChatMessageId(), role: 'user', content: prompt },
            { id: pendingAssistantId, role: 'assistant', content: '', citations: [], route: null, isStreaming: true },
        ]);
        setChatInput('');
        setIsChatStreaming(true);
        try {
            const result = await appApi.ai.streamAssistant({
                notebookId: notebook.id,
                articleId: selectedArticle?.id,
                conversationId: chatConversationId,
                message: prompt,
                onToken: (token) => {
                    setChatMessages((prev) => prev.map((msg) => (
                        msg.id === pendingAssistantId
                            ? { ...msg, content: `${msg.content || ''}${token}` }
                            : msg
                    )));
                },
            });
            setChatConversationId(result.conversationId || chatConversationId);
            setChatMessages((prev) => prev.map((msg) => (
                msg.id === pendingAssistantId
                    ? {
                        ...msg,
                        content: result.reply || msg.content,
                        citations: result.citations || [],
                        route: result.route || null,
                        isStreaming: false,
                    }
                    : msg
            )));
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setChatMessages((prev) => prev.map((msg) => (
                msg.id === pendingAssistantId
                    ? {
                        ...msg,
                        content: `请求失败：${err.message || '请稍后重试'}`,
                        citations: [],
                        route: null,
                        isStreaming: false,
                    }
                    : msg
            )));
        } finally {
            setIsChatStreaming(false);
        }
    };

    const handleSelectArticle = useCallback((article) => {
        if (!article || article.id === selectedArticle?.id) {
            return;
        }

        startTransition(() => {
            setSelectedArticle(article);
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('articleId', article.id);
                return next;
            }, { replace: true });
        });
    }, [selectedArticle?.id, setSearchParams]);

    const buildCitationMeta = useCallback((citation) => {
        const parts = [];
        if (citation.notebookTitle) {
            parts.push(citation.notebookTitle);
        }
        if (Array.isArray(citation.matchedBy) && citation.matchedBy.length > 0) {
            parts.push(citation.matchedBy.join(' + '));
        }
        return parts.join(' · ');
    }, []);

    const handleOpenCitation = useCallback((citation) => {
        if (!citation?.notebookId || !citation?.articleId) {
            return;
        }
        if (citation.notebookId === notebook?.id) {
            const article = notebook.articles.find((item) => item.id === citation.articleId);
            if (article) {
                handleSelectArticle(article);
            }
            return;
        }
        navigate(`/notebook/${citation.notebookId}?articleId=${citation.articleId}`);
    }, [handleSelectArticle, navigate, notebook]);

    const clearChat = () => {
        setChatMessages([]);
        setChatConversationId(null);
    };

    // Note handlers – use modal
    const openNewNote = () => {
        const newNote = { title: '', content: '', type: '笔记', sources: 0, time: '刚刚' };
        setNoteModalData(newNote);
    };

    const openExistingNote = (note) => {
        setNoteModalData(note);
    };

    const handleSaveNote = async (updatedNote) => {
        if (!notebook) return null;
        const savedNote = await appApi.notes.save(notebook.id, updatedNote);
        setNotes((prev) => {
            const exists = prev.find((item) => item.id === savedNote.id);
            if (exists) return prev.map((item) => (item.id === savedNote.id ? savedNote : item));
            return [savedNote, ...prev];
        });
        return savedNote;
    };

    const handleDeleteNote = async (noteId) => {
        if (!notebook) return;
        await appApi.notes.remove(notebook.id, noteId);
        setNotes((prev) => prev.filter((item) => item.id !== noteId));
        if (noteModalData?.id === noteId) {
            setNoteModalData(null);
        }
    };

    const handleSourcesImported = useCallback((detail) => {
        syncNotebookState(detail);
    }, [syncNotebookState]);

    if (isPageLoading) {
        return (
            <div className="notebook-page">
                <div className="nb-empty-center">
                    <h3>正在加载笔记本...</h3>
                </div>
            </div>
        );
    }

    if (pageError || !notebook) {
        return (
            <div className="notebook-page">
                <div className="nb-empty-center">
                    <h3>加载失败</h3>
                    <p>{pageError || '未找到对应的笔记本'}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="notebook-page">
            {/* Top Bar */}
            <header className="nb-topbar">
                <div className="nb-topbar-left">
                    <button className="nb-icon-btn" onClick={() => navigate('/home')} title="返回">{I.back}</button>
                    <div className="nb-topbar-title">
                        <span className="nb-topbar-emoji">{notebook.emoji}</span>
                        <h1>{notebook.title}</h1>
                    </div>
                </div>
                <div className="nb-topbar-right">
                    <button className="nb-icon-btn" onClick={toggleTheme} title="切换主题">{I.theme}</button>
                    <button className="nb-icon-btn" onClick={() => setShowSettings(true)} title="设置">{I.settings}</button>
                    <div className="nb-avatar">{currentUser?.name?.charAt(0) || 'U'}</div>
                </div>
            </header>

            {/* Main Layout */}
            <div className="nb-layout">
                {/* ====== LEFT COLUMN ====== */}
                <div className="nb-left" style={{ width: leftWidth }}>
                    <div className="nb-panel nb-left-top" style={{ height: leftTopH }}>
                        <div className="nb-panel-header">
                            <span className="nb-panel-icon">{I.toc}</span>
                            <span className="nb-panel-title">文章目录</span>
                        </div>
                        <div className="nb-panel-body nb-list-panel-body">
                            {toc.length > 0 ? (
                                <ul className="nb-toc-list nb-list-scroll">
                                    {toc.map((item, idx) => (
                                        <li key={idx} className={`nb-toc-item nb-toc-level-${item.level}`}>
                                            <a href={`#${item.id}`}>{item.title}</a>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint"><p>选择一篇文章查看目录</p></div>
                            )}
                        </div>
                    </div>

                    <div className="nb-resizer nb-resizer-h" onMouseDown={onLeftSplit} />

                    <div className="nb-panel nb-left-bottom" style={{ flex: 1 }}>
                        <div className="nb-panel-header">
                            <span className="nb-panel-icon">{I.paper}</span>
                            <span className="nb-panel-title">来源文章</span>
                            <span className="nb-panel-badge">{notebook.articles.length}</span>
                        </div>
                        <div className="nb-panel-body nb-list-panel-body">
                            {notebook.articles.length > 0 ? (
                                <ul className="nb-article-list nb-list-scroll">
                                    {notebook.articles.map(article => (
                                        <li
                                            key={article.id}
                                            className={`nb-article-item ${selectedArticle?.id === article.id ? 'active' : ''}`}
                                            onClick={() => handleSelectArticle(article)}
                                        >
                                            <span className="nb-article-icon">{getArticleIcon(article.type)}</span>
                                            <span className="nb-article-title-text">{article.title}</span>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint"><p>暂无来源文章</p></div>
                            )}
                        </div>
                    </div>
                </div>

                <div className="nb-resizer nb-resizer-v" onMouseDown={onLeftResize} />

                {/* ====== CENTER COLUMN ====== */}
                <div className="nb-center">
                    {selectedArticle ? (
                        <>
                            <div className="nb-article-toolbar">
                                <div className="nb-toolbar-left">
                                    <h2 className="nb-toolbar-title">{selectedArticle.title}</h2>
                                    <div className="nb-toolbar-meta">
                                        <span>{selectedArticle.author || '未知来源'}</span>
                                        <span>·</span>
                                        <span>{selectedArticle.date || ''}</span>
                                    </div>
                                </div>
                                <div className="nb-toolbar-right">
                                    <button
                                        className={`nb-icon-btn ${showTranslation ? 'active' : ''}`}
                                        title={articleDisplayBlocked ? '正文准备完成后才可翻译' : '翻译'}
                                        onClick={handleTranslate}
                                        disabled={articleDisplayBlocked}
                                    >
                                        {I.translate}
                                    </button>
                                    <button
                                        className={`nb-icon-btn ${showSummary ? 'active' : ''}`}
                                        title={articleDisplayBlocked ? '正文准备完成后才可生成摘要' : 'AI 摘要'}
                                        onClick={handleSummary}
                                        disabled={articleDisplayBlocked}
                                    >
                                        {I.summary}
                                    </button>
                                    <button
                                        className={`nb-icon-btn ${showAiChat ? 'active' : ''}`}
                                        title={articleDisplayBlocked ? '正文准备完成后才可针对文章问答' : 'AI 助手'}
                                        onClick={handleToggleChat}
                                        disabled={articleDisplayBlocked}
                                    >
                                        {I.chat}
                                    </button>
                                    <div className="nb-toolbar-menu-wrapper" ref={menuRef}>
                                        <button className="nb-icon-btn" title="更多设置" onClick={() => setShowArticleMenu(!showArticleMenu)}>{I.more}</button>
                                        {showArticleMenu && (
                                            <div className="nb-toolbar-dropdown">
                                                <div className="nb-dropdown-section">
                                                    <label className="nb-dropdown-label">{I.font} 字体大小</label>
                                                    <div className="nb-dropdown-slider">
                                                        <span>小</span>
                                                        <input type="range" min="0.8" max="1.4" step="0.05" value={fontSize} onChange={(e) => setFontSize(parseFloat(e.target.value))} />
                                                        <span className="nb-slider-value">{fontSize.toFixed(2)}em</span>
                                                        <span>大</span>
                                                    </div>
                                                </div>
                                                <div className="nb-dropdown-section">
                                                    <label className="nb-dropdown-label">页面宽度</label>
                                                    <div className="nb-dropdown-slider">
                                                        <span>窄</span>
                                                        <input type="range" min="500" max="1000" step="20" value={pageWidth} onChange={(e) => setPageWidth(parseInt(e.target.value))} />
                                                        <span className="nb-slider-value">{pageWidth}</span>
                                                        <span>宽</span>
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            <div className="nb-center-body">
                                <ArticleContentPane
                                    articleId={selectedArticle.id}
                                    articleTitle={selectedArticle.title}
                                    articleFileUrl={selectedArticle.fileUrl}
                                    articleProcessingHint={selectedArticle.processingHint}
                                    articleDisplayBlocked={articleDisplayBlocked}
                                    articleRenderMode={articleRenderMode}
                                    renderedArticleContent={renderedArticleContent}
                                    fontSize={fontSize}
                                    pageWidth={pageWidth}
                                    showSummary={showSummary}
                                    summaryLoading={summaryLoading}
                                    summaryText={summaryText}
                                    showTranslation={showTranslation}
                                    translationLoading={translationLoading}
                                    translationText={translationText}
                                    translationLanguage={translationLanguage}
                                    translationError={translationError}
                                    setShowSummary={setShowSummary}
                                    setShowTranslation={setShowTranslation}
                                />
                            </div>
                        </>
                    ) : (
                        <div className="nb-empty-center">
                            <div className="nb-empty-center-icon">{I.paper}</div>
                            <h3>选择一篇文章开始阅读</h3>
                            <p>点击左侧来源文章列表中的任意文章</p>
                        </div>
                    )}
                </div>

                <div className="nb-resizer nb-resizer-v" onMouseDown={onRightResize} />

                {/* ====== RIGHT COLUMN ====== */}
                <div className="nb-right" style={{ width: rightWidth }}>
                    {showAiChat ? (
                        <div className="nb-panel nb-right-full nb-chat-panel">
                            <div className="nb-panel-header nb-chat-header">
                                <span className="nb-panel-title">AI 助手</span>
                                <div className="nb-chat-header-actions">
                                    <button className="nb-icon-btn-sm" onClick={clearChat} title="清空对话">{I.deleteChat}</button>
                                    <button className="nb-icon-btn-sm" onClick={() => setShowAiChat(false)} title="关闭">{I.close}</button>
                                </div>
                            </div>
                            <div className="nb-chat-messages">
                                {chatMessages.length === 0 && (
                                    <div className="nb-chat-welcome">
                                        <div className="nb-chat-welcome-icon">{I.sparkle}</div>
                                        <p className="nb-chat-welcome-title">有什么想问的?</p>
                                        <p className="nb-chat-welcome-hint">已加载当前文章内容，你可以提问、讨论或请求分析</p>
                                        <div className="nb-chat-quick-actions">
                                            <button onClick={() => setChatInput('创建详细摘要')}>创建详细摘要</button>
                                        </div>
                                    </div>
                                )}
                                {chatMessages.map((msg, idx) => (
                                    <div key={msg.id || idx} className={`nb-chat-msg nb-chat-msg-${msg.role}`}>
                                        <div className={`nb-chat-bubble nb-chat-bubble-${msg.role}`}>
                                            {msg.role === 'assistant' && msg.route && (
                                                <div className="nb-chat-route-chip">
                                                    {CHAT_ROUTE_LABELS[msg.route] || msg.route}
                                                </div>
                                            )}
                                            {msg.content ? (
                                                <div className="nb-chat-markdown">
                                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                                        {msg.content}
                                                    </ReactMarkdown>
                                                </div>
                                            ) : (
                                                <div>{msg.isStreaming ? '正在生成...' : ''}</div>
                                            )}
                                            {msg.role === 'assistant' && Array.isArray(msg.citations) && msg.citations.length > 0 && (
                                                <div className="nb-chat-citations">
                                                    {msg.citations.map((citation) => (
                                                        <button
                                                            key={`${citation.notebookId}-${citation.articleId}`}
                                                            type="button"
                                                            className="nb-chat-citation-card"
                                                            onClick={() => handleOpenCitation(citation)}
                                                        >
                                                            <span className="nb-chat-citation-title">{citation.title}</span>
                                                            <span className="nb-chat-citation-meta">{buildCitationMeta(citation)}</span>
                                                            {citation.snippet && (
                                                                <span className="nb-chat-citation-snippet">{citation.snippet}</span>
                                                            )}
                                                        </button>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                            <div className="nb-chat-input-area">
                                <div className="nb-chat-input-wrapper">
                                    <input className="nb-chat-input" placeholder="输入你的问题..." value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSendChat()} />
                                    <button className="nb-chat-send-btn" onClick={handleSendChat} disabled={!chatInput.trim() || isChatStreaming}>{I.send}</button>
                                </div>
                            </div>
                        </div>
                    ) : sourceExpanded ? (
                        <div className="nb-panel nb-right-full">
                            <SourcePanel
                                notebookId={notebook.id}
                                searchQuery={searchQuery}
                                setSearchQuery={setSearchQuery}
                                onAddSource={() => setShowAddSource(true)}
                                onCollapse={() => setSourceExpanded(false)}
                                onSourcesImported={handleSourcesImported}
                            />
                        </div>
                    ) : (
                        <>
                            <div className="nb-panel nb-right-top" style={{ height: rightTopH }}>
                                <SourcePanel
                                    notebookId={notebook.id}
                                    searchQuery={searchQuery}
                                    setSearchQuery={setSearchQuery}
                                    onAddSource={() => setShowAddSource(true)}
                                    onExpand={() => setSourceExpanded(true)}
                                    onSourcesImported={handleSourcesImported}
                                />
                            </div>

                            <div className="nb-resizer nb-resizer-h" onMouseDown={onRightSplit} />

                            {/* Notes Panel */}
                            <div className="nb-panel nb-right-bottom" style={{ flex: 1 }}>
                                <div className="nb-panel-header">
                                    <span className="nb-panel-icon">{I.note}</span>
                                    <span className="nb-panel-title">笔记</span>
                                    <span className="nb-panel-badge">{notes.length}</span>
                                </div>
                                <div className="nb-panel-body nb-notes-body">
                                    <div className="nb-notes-list">
                                        {notes.map(note => (
                                            <div key={note.id} className="nb-note-card">
                                                <div className="nb-note-card-inner" onClick={() => openExistingNote(note)}>
                                                    <div className="nb-note-card-icon">{I.edit}</div>
                                                    <div className="nb-note-card-info">
                                                        <span className="nb-note-card-title">{note.title}</span>
                                                        <span className="nb-note-card-sub">{note.type} · {note.sources} 个来源 · {note.time}</span>
                                                    </div>
                                                    <button className="nb-note-card-more" onClick={(e) => { e.stopPropagation(); handleDeleteNote(note.id); }} title="删除">{I.more}</button>
                                                </div>
                                            </div>
                                        ))}
                                    </div>

                                    <div className="nb-note-add-bottom">
                                        <button className="nb-note-add-pill" onClick={openNewNote}>
                                            {I.addNote}
                                            <span>添加笔记</span>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </>
                    )}
                </div>
            </div>

            {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
            {showAddSource && (
                <AddSourceModal
                    notebookId={notebook.id}
                    onClose={() => setShowAddSource(false)}
                    onImported={handleSourcesImported}
                />
            )}
            {noteModalData && (
                <NoteModal
                    note={noteModalData}
                    onClose={() => setNoteModalData(null)}
                    onSave={handleSaveNote}
                    onDelete={handleDeleteNote}
                />
            )}
        </div>
    );
}
