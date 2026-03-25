import { memo, startTransition, useState, useCallback, useRef, useEffect, useMemo, useDeferredValue } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { appApi, clearStoredSession, getStoredSession, isAuthError } from '../services/appApi';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Document, Page, pdfjs } from 'react-pdf';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import SettingsModal from '../components/SettingsModal';
import InlineEditableText from '../components/common/InlineEditableText';
import ErrorBanner from '../components/common/ErrorBanner';
import AddSourceModal from '../components/AddSourceModal';
import SourcePanel from '../components/SourcePanel';
import NoteModal from '../components/NoteModal';
import SourceActionModal from '../components/SourceActionModal';
import './NotebookPage.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
    'pdfjs-dist/build/pdf.worker.min.mjs',
    import.meta.url,
).toString();

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
        && (entry?.matchIndex || 0) === (right[index]?.matchIndex || 0)
    ));
}

function normalizeHeadingText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizePdfLookupText(value) {
    return normalizeHeadingText(value)
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\u4e00-\u9fff]+/gu, '');
}

function formatArticleDate(value) {
    if (!value) return '';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value);
    }
    const year = String(parsed.getFullYear()).slice(-2);
    const month = String(parsed.getMonth() + 1).padStart(2, '0');
    const day = String(parsed.getDate()).padStart(2, '0');
    const hours = String(parsed.getHours()).padStart(2, '0');
    const minutes = String(parsed.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}-${minutes}`;
}

function getArticleBodyElement(container) {
    return container?.querySelector('[data-role="article-body"]') || null;
}

function collectRenderedToc(container) {
    if (!container) return [];
    return Array.from(container.querySelectorAll('h1, h2, h3, h4'))
        .map((heading, index) => {
            const title = normalizeHeadingText(heading.textContent);
            if (!title) return null;
            return {
                id: heading.id || '',
                title,
                level: Number(heading.tagName.slice(1)) || 2,
                matchIndex: index,
            };
        })
        .filter(Boolean);
}

async function resolvePdfDestinationPage(pdf, destination) {
    const dest = Array.isArray(destination)
        ? destination
        : (destination ? await pdf.getDestination(destination) : null);
    const ref = dest?.[0];
    if (!ref) return null;
    const pageIndex = await pdf.getPageIndex(ref);
    return pageIndex + 1;
}

async function buildPdfOutlineItems(pdf, items, depth = 1, fallbackOrder = { current: 1 }) {
    if (!Array.isArray(items) || items.length === 0) return [];
    const result = [];
    for (const item of items) {
        const pageNumber = await resolvePdfDestinationPage(pdf, item.dest).catch(() => null);
        const currentIndex = fallbackOrder.current++;
        result.push({
            id: `pdf-outline-${currentIndex}`,
            title: normalizeHeadingText(item.title),
            level: Math.min(depth, 4),
            pageNumber,
            children: await buildPdfOutlineItems(pdf, item.items, depth + 1, fallbackOrder),
        });
    }
    return result;
}

function flattenPdfOutline(items) {
    const flat = [];
    const walk = (nodes) => {
        for (const node of nodes || []) {
            flat.push({
                id: node.id,
                title: node.title,
                level: node.level,
                pageNumber: node.pageNumber,
            });
            if (Array.isArray(node.children) && node.children.length > 0) {
                walk(node.children);
            }
        }
    };
    walk(items);
    return flat;
}

async function buildPdfPageTextIndex(pdf) {
    const pages = [];
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
        const page = await pdf.getPage(pageNumber);
        const textContent = await page.getTextContent();
        const pageText = textContent.items
            .map((item) => (typeof item?.str === 'string' ? item.str : ''))
            .join(' ');
        pages.push({
            pageNumber,
            normalizedText: normalizePdfLookupText(pageText),
        });
    }
    return pages;
}

async function buildGeneratedPdfToc(pdf, fallbackToc) {
    if (!Array.isArray(fallbackToc) || fallbackToc.length === 0) return [];
    const pageTextIndex = await buildPdfPageTextIndex(pdf);
    return fallbackToc.map((item, index) => {
        const title = normalizeHeadingText(item.title);
        const normalizedTitle = normalizePdfLookupText(title);
        const matchedPage = pageTextIndex.find((page) => normalizedTitle && page.normalizedText.includes(normalizedTitle));
        return {
            id: item.id || `pdf-generated-${index + 1}`,
            title,
            level: item.level || 2,
            pageNumber: matchedPage?.pageNumber || null,
        };
    });
}

function resolveHeadingTarget(container, tocItem) {
    if (!container || !tocItem) return null;
    if (tocItem.id) {
        const escapedId = typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
            ? CSS.escape(tocItem.id)
            : tocItem.id.replace(/"/g, '\\"');
        const byId = container.querySelector(`#${escapedId}`);
        if (byId) {
            return byId;
        }
    }

    const expectedTitle = normalizeHeadingText(tocItem.title);
    const matches = Array.from(container.querySelectorAll('h1, h2, h3, h4, h5, h6'))
        .filter((heading) => normalizeHeadingText(heading.textContent) === expectedTitle);
    return matches[tocItem.matchIndex || 0] || matches[0] || null;
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
    article_grounded: '当前文章',
    recommendation: '来自你的笔记',
    notebook_research: '在当前笔记研究',
    general: '通用回答',
    ambiguous: '待确认范围',
};

const ARTICLE_MARKDOWN_REMARK_PLUGINS = [remarkGfm];
const ARTICLE_MARKDOWN_REHYPE_PLUGINS = [rehypeRaw, rehypeSlug];

const markdownComponents = {
    code({ inline, className, children, ...props }) {
        const match = /language-(\w+)/.exec(className || '');
        if (inline) {
            return <code className={className} {...props}>{children}</code>;
        }
        return (
            <SyntaxHighlighter
                style={oneDark}
                language={match?.[1] || 'text'}
                PreTag="div"
                customStyle={{ borderRadius: '16px', margin: 0, fontSize: '0.86em' }}
                {...props}
            >
                {String(children).replace(/\n$/, '')}
            </SyntaxHighlighter>
        );
    },
};

const MarkdownDocument = memo(function MarkdownDocument({ content, className }) {
    if (!content?.trim()) {
        return null;
    }

    return (
        <div className={className}>
            <ReactMarkdown
                remarkPlugins={ARTICLE_MARKDOWN_REMARK_PLUGINS}
                rehypePlugins={ARTICLE_MARKDOWN_REHYPE_PLUGINS}
                components={markdownComponents}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
});

const PdfDocumentPane = memo(function PdfDocumentPane({
    fileUrl,
    fallbackToc,
    pageWidth,
    onOutlineChange,
    requestedPageNumber,
    onPageJumpHandled,
}) {
    const [numPages, setNumPages] = useState(0);
    const [loadError, setLoadError] = useState('');
    const [pdfData, setPdfData] = useState(null);
    const [resolvedPageWidth, setResolvedPageWidth] = useState(pageWidth);
    const viewportRef = useRef(null);
    const pageRefs = useRef(new Map());
    const session = getStoredSession();
    const pdfFile = useMemo(() => (
        pdfData ? { data: pdfData } : null
    ), [pdfData]);

    useEffect(() => {
        setNumPages(0);
        setLoadError('');
        setPdfData(null);
        onOutlineChange([]);
        pageRefs.current = new Map();
    }, [fileUrl, onOutlineChange]);

    useEffect(() => {
        if (!fileUrl) {
            return undefined;
        }
        const controller = new AbortController();
        let cancelled = false;
        const loadPdfBytes = async () => {
            try {
                setLoadError('');
                const absoluteUrl = /^https?:\/\//.test(fileUrl)
                    ? fileUrl
                    : new URL(fileUrl, window.location.origin).toString();
                const response = await fetch(absoluteUrl, {
                    headers: {
                        ...(session?.token ? { Authorization: `Bearer ${session.token}` } : {}),
                    },
                    signal: controller.signal,
                });
                if (!response.ok) {
                    throw new Error(`PDF 请求失败 (${response.status})`);
                }
                const data = new Uint8Array(await response.arrayBuffer());
                if (!data.byteLength) {
                    throw new Error('PDF 文件为空');
                }
                if (!cancelled) {
                    setPdfData(data);
                }
            } catch (error) {
                if (controller.signal.aborted || cancelled) {
                    return;
                }
                const message = error instanceof Error ? error.message : 'PDF 加载失败';
                console.error('pdf.fetch_failed', { fileUrl, message });
                setLoadError(message);
            }
        };
        loadPdfBytes();
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [fileUrl, session?.token]);

    useEffect(() => {
        const element = viewportRef.current;
        if (!element) return undefined;
        const updateWidth = () => {
            const nextWidth = Math.max(320, Math.min(pageWidth, element.clientWidth - 48));
            setResolvedPageWidth(nextWidth);
        };
        updateWidth();
        const observer = new ResizeObserver(updateWidth);
        observer.observe(element);
        return () => observer.disconnect();
    }, [pageWidth]);

    useEffect(() => {
        if (!requestedPageNumber) return;
        const target = pageRefs.current.get(requestedPageNumber);
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        onPageJumpHandled();
    }, [onPageJumpHandled, requestedPageNumber]);

    const handleLoadSuccess = useCallback(async (pdf) => {
        setNumPages(pdf.numPages);
        setLoadError('');
        try {
            const outline = await pdf.getOutline();
            if (Array.isArray(outline) && outline.length > 0) {
                const normalizedOutline = await buildPdfOutlineItems(pdf, outline);
                onOutlineChange(flattenPdfOutline(normalizedOutline));
                return;
            }
            const generatedOutline = await buildGeneratedPdfToc(pdf, fallbackToc);
            onOutlineChange(generatedOutline);
        } catch {
            onOutlineChange([]);
        }
    }, [fallbackToc, onOutlineChange]);

    if (!fileUrl) {
        return <div className="nb-empty-hint"><p>PDF 文件暂不可访问</p></div>;
    }

    if (loadError) {
        return (
            <div className="nb-pdf-body" data-role="article-body" ref={viewportRef}>
                <div className="nb-empty-hint"><p>{loadError}</p></div>
            </div>
        );
    }

    if (!pdfFile) {
        return (
            <div className="nb-pdf-body" data-role="article-body" ref={viewportRef}>
                <div className="nb-pdf-loading">正在加载 PDF...</div>
            </div>
        );
    }

    return (
        <div className="nb-pdf-body" data-role="article-body" ref={viewportRef}>
            <Document
                file={pdfFile}
                loading={<div className="nb-pdf-loading">正在加载 PDF...</div>}
                onLoadError={(error) => setLoadError(error?.message || 'PDF 加载失败')}
                onLoadSuccess={handleLoadSuccess}
            >
                {Array.from({ length: numPages }, (_, index) => {
                    const pageNumber = index + 1;
                    return (
                        <div
                            key={`pdf-page-${pageNumber}`}
                            className="nb-pdf-page"
                            ref={(node) => {
                                if (node) {
                                    pageRefs.current.set(pageNumber, node);
                                } else {
                                    pageRefs.current.delete(pageNumber);
                                }
                            }}
                        >
                            <Page
                                pageNumber={pageNumber}
                                renderAnnotationLayer
                                renderTextLayer
                                width={resolvedPageWidth}
                            />
                        </div>
                    );
                })}
            </Document>
        </div>
    );
});

const ArticleContentPane = memo(function ArticleContentPane({
    articleId,
    articleFileUrl,
    articleProcessingHint,
    articleDisplayBlocked,
    articleRenderMode,
    renderedArticleContent,
    fallbackToc,
    fontSize,
    pageWidth,
    pdfRequestedPageNumber,
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
    setPdfOutline,
    setPdfRequestedPageNumber,
    onCopySummary,
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
                    <div className="nb-summary-body" onCopy={summaryLoading ? undefined : onCopySummary}>
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
            ) : articleRenderMode === 'pdf' && !showTranslation ? (
                <PdfDocumentPane
                    fileUrl={articleFileUrl}
                    fallbackToc={fallbackToc}
                    pageWidth={pageWidth}
                    requestedPageNumber={pdfRequestedPageNumber}
                    onOutlineChange={setPdfOutline}
                    onPageJumpHandled={() => setPdfRequestedPageNumber(null)}
                />
            ) : showTranslation && translationText ? (
                <div className="nb-article-markdown" data-role="article-body">
                    <MarkdownDocument content={deferredArticleContent} />
                </div>
            ) : (
                <div className="nb-article-markdown" data-role="article-body">
                    <MarkdownDocument content={deferredArticleContent} />
                </div>
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
    openLink: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" /></svg>,
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
    const [layoutMode, setLayoutMode] = useState('triple');
    const [showAddSource, setShowAddSource] = useState(false);
    const [sourceExpanded, setSourceExpanded] = useState(false);
    const [showArticleMenu, setShowArticleMenu] = useState(false);
    const [articleContextMenu, setArticleContextMenu] = useState(null);
    const [articleActionPendingId, setArticleActionPendingId] = useState(null);
    const [sourceActionModal, setSourceActionModal] = useState(null);
    const [renderedToc, setRenderedToc] = useState([]);
    const [pdfOutline, setPdfOutline] = useState([]);
    const [pdfRequestedPageNumber, setPdfRequestedPageNumber] = useState(null);
    const [isPageLoading, setIsPageLoading] = useState(true);
    const [pageError, setPageError] = useState('');
    const menuRef = useRef(null);
    const articleContextMenuRef = useRef(null);
    const centerBodyRef = useRef(null);

    // AI features
    const [showSummary, setShowSummary] = useState(false);
    const [summaryText, setSummaryText] = useState('');
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [showAiChat, setShowAiChat] = useState(false);
    const [chatScope, setChatScope] = useState('article');
    const [chatMessages, setChatMessages] = useState([]);
    const [chatConversationId, setChatConversationId] = useState(null);
    const [chatInput, setChatInput] = useState('');
    const [isChatStreaming, setIsChatStreaming] = useState(false);
    const [chatReadingCursor, setChatReadingCursor] = useState({ page: null, sectionId: null, blockId: null });
    const [showTranslation, setShowTranslation] = useState(false);
    const [translationText, setTranslationText] = useState('');
    const [translationLoading, setTranslationLoading] = useState(false);
    const [translationLanguage, setTranslationLanguage] = useState('');
    const [translationError, setTranslationError] = useState('');
    const [readerSearchQuery, setReaderSearchQuery] = useState('');
    const [readerSearchIndex, setReaderSearchIndex] = useState(0);

    // Article settings
    const [fontSize, setFontSize] = useState(1.05);
    const [pageWidth, setPageWidth] = useState(720);

    // Notes state
    const [notes, setNotes] = useState([]);
    const [noteModalData, setNoteModalData] = useState(null); // null = closed, object = open


    const redirectToLogin = useCallback(() => {
        clearStoredSession();
        navigate('/login', { replace: true });
    }, [navigate]);

    const trackAiEvent = useCallback((payload) => {
        if (!notebook?.id) return;
        void appApi.ai.trackAiEvent({
            notebookId: notebook.id,
            ...payload,
        }).catch(() => {});
    }, [notebook?.id]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setShowArticleMenu(false);
            }
            if (articleContextMenuRef.current && !articleContextMenuRef.current.contains(e.target)) {
                setArticleContextMenu(null);
            }
        };
        const handleEscape = (event) => {
            if (event.key === 'Escape') {
                setShowArticleMenu(false);
                setArticleContextMenu(null);
            }
        };
        document.addEventListener('mousedown', handler);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handler);
            document.removeEventListener('keydown', handleEscape);
        };
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
        setPdfOutline([]);
        setPdfRequestedPageNumber(null);
        setChatReadingCursor({
            page: null,
            sectionId: selectedArticle?.toc?.[0]?.id || null,
            blockId: null,
        });
    }, [selectedArticle?.id, selectedArticle?.toc]);

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
    const articleCanDisplayPdf = articleRenderMode === 'pdf' && Boolean(selectedArticle?.fileUrl);
    const articleContentReady = selectedArticle?.contentReady ?? Boolean(selectedArticle?.content?.trim());
    const articleDisplayBlocked = Boolean(selectedArticle) && !articleCanDisplayPdf && !articleContentReady;
    const articleAiBlocked = !articleContentReady;
    const fallbackPdfToc = useMemo(() => (
        Array.isArray(selectedArticle?.toc) ? selectedArticle.toc : []
    ), [selectedArticle?.toc]);
    const toc = useMemo(() => {
        if (articleRenderMode === 'pdf') {
            return pdfOutline.length > 0 ? pdfOutline : fallbackPdfToc;
        }
        return renderedToc;
    }, [articleRenderMode, fallbackPdfToc, pdfOutline, renderedToc]);
    const strippedContent = useMemo(() => (
        selectedArticle && articleRenderMode !== 'pdf' && !articleDisplayBlocked
            ? stripFirstH1(selectedArticle.content)
            : ''
    ), [selectedArticle, articleDisplayBlocked, articleRenderMode]);
    const renderedArticleContent = useMemo(() => (
        showTranslation && translationText ? stripFirstH1(translationText) : strippedContent
    ), [showTranslation, translationText, strippedContent]);
    const readerSearchMatches = useMemo(() => {
        if (!readerSearchQuery.trim()) return [];
        const lower = renderedArticleContent.toLowerCase();
        const keyword = readerSearchQuery.trim().toLowerCase();
        const matches = [];
        let cursor = lower.indexOf(keyword);
        while (cursor !== -1 && matches.length < 100) {
            matches.push(cursor);
            cursor = lower.indexOf(keyword, cursor + keyword.length);
        }
        return matches;
    }, [readerSearchQuery, renderedArticleContent]);

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
            setSummaryText(result.summaryText || result.summary || '');
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
        if (!selectedArticle) setChatScope('notebook');
    };

    const handleSendChat = async () => {
        if (!chatInput.trim() || !notebook || isChatStreaming) return;
        const prompt = chatInput.trim();
        const isFollowUp = Boolean(chatConversationId || chatMessages.some((item) => item.role === 'assistant'));
        const pendingAssistantId = createChatMessageId();
        setChatMessages((prev) => [
            ...prev,
            { id: createChatMessageId(), role: 'user', content: prompt },
            {
                id: pendingAssistantId,
                role: 'assistant',
                content: '',
                relatedArticles: [],
                evidenceSpans: [],
                route: null,
                routeBadge: '',
                isStreaming: true,
            },
        ]);
        setChatInput('');
        setIsChatStreaming(true);
        if (isFollowUp) {
            trackAiEvent({
                operation: 'chat',
                action: 'follow_up',
                route: 'none',
                articleId: selectedArticle?.id || null,
                conversationId: chatConversationId,
            });
        }
        const recentTurns = chatMessages
            .slice(-6)
            .map((item) => ({ role: item.role, content: item.content || '' }))
            .filter((item) => item.content.trim());
        try {
            const result = await appApi.ai.streamAssistant({
                notebookId: notebook.id,
                articleId: chatScope === 'article' ? selectedArticle?.id : null,
                conversationId: chatConversationId,
                message: prompt,
                readingCursor: chatReadingCursor,
                recentHighlights: [],
                recentTurns,
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
                        content: result.answer || msg.content,
                        relatedArticles: result.relatedArticles || [],
                        evidenceSpans: result.evidenceSpans || [],
                        route: result.route || null,
                        routeBadge: result.routeBadge || '',
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
                        relatedArticles: [],
                        evidenceSpans: [],
                        route: null,
                        routeBadge: '',
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

        setArticleContextMenu(null);
        startTransition(() => {
            setSelectedArticle(article);
            setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('articleId', article.id);
                return next;
            }, { replace: true });
            setChatReadingCursor({
                page: null,
                sectionId: article.toc?.[0]?.id || null,
                blockId: null,
            });
        });
    }, [selectedArticle?.id, setSearchParams]);

    const handleTocClick = useCallback((event, tocItem) => {
        event.preventDefault();
        if (articleRenderMode === 'pdf') {
            if (tocItem?.pageNumber) {
                setPdfRequestedPageNumber(tocItem.pageNumber);
                setChatReadingCursor({
                    page: tocItem.pageNumber,
                    sectionId: tocItem.id || null,
                    blockId: null,
                });
            }
            return;
        }
        const container = centerBodyRef.current;
        if (!container) return;

        const articleBody = getArticleBodyElement(container);
        const target = resolveHeadingTarget(articleBody, tocItem);
        if (!target) return;

        const containerRect = container.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const nextScrollTop = container.scrollTop + (targetRect.top - containerRect.top) - 12;
        container.scrollTo({
            top: Math.max(nextScrollTop, 0),
            behavior: 'smooth',
        });
        setChatReadingCursor({
            page: null,
            sectionId: tocItem?.id || null,
            blockId: null,
        });
    }, [articleRenderMode]);

    useEffect(() => {
        if (!selectedArticle || articleDisplayBlocked || articleRenderMode === 'pdf') {
            setRenderedToc([]);
            return undefined;
        }

        const frameId = window.requestAnimationFrame(() => {
            const articleBody = getArticleBodyElement(centerBodyRef.current);
            setRenderedToc(collectRenderedToc(articleBody));
        });

        const container = centerBodyRef.current;
        const articleBody = getArticleBodyElement(container);
        if (!container || !articleBody) return () => window.cancelAnimationFrame(frameId);

        const headings = Array.from(articleBody.querySelectorAll('h1, h2, h3, h4'));
        const syncScrollSpy = () => {
            const currentHeading = headings.findLast((heading) => heading.getBoundingClientRect().top - container.getBoundingClientRect().top < 96);
            if (currentHeading?.id) {
                setChatReadingCursor((prev) => ({ ...prev, sectionId: currentHeading.id }));
            }
        };
        container.addEventListener('scroll', syncScrollSpy);

        return () => {
            window.cancelAnimationFrame(frameId);
            container.removeEventListener('scroll', syncScrollSpy);
        };
    }, [
        articleDisplayBlocked,
        articleRenderMode,
        renderedArticleContent,
        selectedArticle?.id,
        showTranslation,
        translationText,
    ]);

    const handleOpenArticleContextMenu = useCallback((event, article) => {
        event.preventDefault();
        const menuWidth = 196;
        const menuHeight = 120;
        const x = Math.min(event.clientX, window.innerWidth - menuWidth - 16);
        const y = Math.min(event.clientY, window.innerHeight - menuHeight - 16);
        setArticleContextMenu({
            articleId: article.id,
            articleTitle: article.title,
            x: Math.max(x, 12),
            y: Math.max(y, 12),
        });
    }, []);

    const openRenameArticleModal = useCallback((articleId, currentTitle) => {
        setArticleContextMenu(null);
        setSourceActionModal({
            mode: 'rename',
            articleId,
            articleTitle: currentTitle || '',
            nextTitle: currentTitle || '',
            error: '',
        });
    }, []);

    const openDeleteArticleModal = useCallback((articleId, articleTitle) => {
        setArticleContextMenu(null);
        setSourceActionModal({
            mode: 'delete',
            articleId,
            articleTitle: articleTitle || '',
            nextTitle: articleTitle || '',
            error: '',
        });
    }, []);

    const handleConfirmSourceAction = useCallback(async () => {
        if (!notebook?.id || !sourceActionModal?.articleId) return;
        try {
            setArticleActionPendingId(sourceActionModal.articleId);
            if (sourceActionModal.mode === 'rename') {
                const trimmedTitle = sourceActionModal.nextTitle.trim();
                if (!trimmedTitle || trimmedTitle === sourceActionModal.articleTitle) {
                    setSourceActionModal(null);
                    return;
                }
                const detail = await appApi.sources.updateArticle({
                    notebookId: notebook.id,
                    articleId: sourceActionModal.articleId,
                    title: trimmedTitle,
                });
                syncNotebookState(detail);
                setSourceActionModal(null);
                return;
            }

            const detail = await appApi.sources.deleteArticle({
                notebookId: notebook.id,
                articleId: sourceActionModal.articleId,
            });
            syncNotebookState(detail);
            setSourceActionModal(null);
            if (selectedArticle?.id === sourceActionModal.articleId) {
                startTransition(() => {
                    setSearchParams((prev) => {
                        const next = new URLSearchParams(prev);
                        const nextSelectedId = detail.articles?.[0]?.id;
                        if (nextSelectedId) {
                            next.set('articleId', nextSelectedId);
                        } else {
                            next.delete('articleId');
                        }
                        return next;
                    }, { replace: true });
                });
            }
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setSourceActionModal((prev) => (
                prev
                    ? { ...prev, error: err.message || (prev.mode === 'rename' ? '重命名来源失败' : '删除来源失败') }
                    : prev
            ));
        } finally {
            setArticleActionPendingId(null);
        }
    }, [notebook?.id, redirectToLogin, selectedArticle?.id, setSearchParams, sourceActionModal, syncNotebookState]);

    const buildCitationMeta = useCallback((citation) => {
        const parts = [];
        if (citation.notebookTitle) {
            parts.push(citation.notebookTitle);
        }
        if (citation.whySimilar) {
            parts.push(citation.whySimilar);
        }
        return parts.join(' · ');
    }, []);

    const handleOpenCitation = useCallback((citation, route = 'none') => {
        if (!citation?.notebookId || !citation?.articleId) {
            return;
        }
        trackAiEvent({
            operation: 'chat',
            action: 'citation_open',
            route,
            articleId: citation.articleId,
            conversationId: chatConversationId,
        });
        if (citation.notebookId === notebook?.id) {
            const article = notebook.articles.find((item) => item.id === citation.articleId);
            if (article) {
                handleSelectArticle(article);
            }
            return;
        }
        navigate(`/notebook/${citation.notebookId}?articleId=${citation.articleId}`);
    }, [chatConversationId, handleSelectArticle, navigate, notebook, trackAiEvent]);

    const handleCopySummary = useCallback(() => {
        if (!summaryText.trim()) return;
        trackAiEvent({
            operation: 'summary',
            action: 'summary_copy',
            route: 'none',
            articleId: selectedArticle?.id || null,
            conversationId: null,
        });
    }, [selectedArticle?.id, summaryText, trackAiEvent]);

    const handleCopyAssistant = useCallback((msg) => {
        if (!msg?.content?.trim()) return;
        trackAiEvent({
            operation: 'chat',
            action: 'answer_copy',
            route: msg.route || 'none',
            articleId: selectedArticle?.id || null,
            conversationId: chatConversationId,
        });
    }, [chatConversationId, selectedArticle?.id, trackAiEvent]);

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

    const handleRetryArticle = useCallback(async (articleId) => {
        if (!notebook?.id) return;
        try {
            setArticleActionPendingId(articleId);
            const detail = await appApi.sources.retryArticle({ notebookId: notebook.id, articleId });
            syncNotebookState(detail);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setPageError(err.message || '重试来源失败');
        } finally {
            setArticleActionPendingId(null);
        }
    }, [notebook?.id, redirectToLogin, syncNotebookState]);

    const handleRenameNotebook = useCallback(async (nextTitle) => {
        if (!notebook?.id) return;
        const detail = await appApi.notebooks.update(notebook.id, { title: nextTitle });
        setNotebook((prev) => ({ ...prev, ...detail }));
    }, [notebook?.id]);

    useEffect(() => {
        if (notebook && notebook.articles.length === 0 && !showAddSource) {
            setShowAddSource(true);
        }
    }, [notebook, showAddSource]);

    if (isPageLoading) {
        return (
            <div className="notebook-page">
                <div className="nb-empty-center">
                    <div className="nb-skeleton-group">
                        <div className="nb-skeleton-line short" />
                        <div className="nb-skeleton-line" />
                        <div className="nb-skeleton-line medium" />
                    </div>
                </div>
            </div>
        );
    }

    if (pageError || !notebook) {
        return (
            <div className="notebook-page">
                <div className="nb-empty-center">
                    <ErrorBanner title="加载失败" message={pageError || '未找到对应的笔记本'} actionLabel="重试" onAction={() => window.location.reload()} />
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
                        <InlineEditableText
                            value={notebook.title}
                            className="nb-topbar-title-trigger"
                            inputClassName="nb-topbar-title-input"
                            onSave={handleRenameNotebook}
                        />
                    </div>
                </div>
                <div className="nb-topbar-right">
                    <button className="nb-icon-btn" onClick={toggleTheme} title="切换主题">{I.theme}</button>
                    <button className="nb-icon-btn" onClick={() => setShowSettings(true)} title="设置">{I.settings}</button>
                    <div className="nb-avatar">{currentUser?.name?.charAt(0) || 'U'}</div>
                </div>
            </header>

            {/* Main Layout */}
            <div className="nb-layout" data-layout={layoutMode}>
                {/* ====== LEFT COLUMN ====== */}
                {layoutMode !== 'reader' ? (
                <div className="nb-left">
                    <div className="nb-panel nb-left-top">
                        <div className="nb-panel-header">
                            <span className="nb-panel-icon">{I.toc}</span>
                            <span className="nb-panel-title">文章目录</span>
                            <button type="button" className="nb-panel-collapse" onClick={() => setLayoutMode('reader')}>收起侧栏</button>
                        </div>
                        <div className="nb-panel-body nb-list-panel-body">
                            {toc.length > 0 ? (
                                <ul className="nb-toc-list nb-list-scroll">
                                    {toc.map((item, idx) => (
                                        <li key={`${item.id || item.title}-${item.matchIndex || 0}-${idx}`} className={`nb-toc-item nb-toc-level-${item.level}`}>
                                            <a href={`#${item.id}`} onClick={(event) => handleTocClick(event, item)}>{item.title}</a>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint"><p>选择一篇文章查看目录</p></div>
                            )}
                        </div>
                    </div>

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
                                            onContextMenu={(event) => handleOpenArticleContextMenu(event, article)}
                                            title="右键可编辑或删除来源"
                                        >
                                            <span className="nb-article-icon">{getArticleIcon(article.type)}</span>
                                            <span className="nb-article-title-text">{article.title}</span>
                                            <span className={`nb-status-pill ${article.parseStatus === 'failed' ? 'failed' : (article.contentReady ? 'ready' : 'processing')}`}>
                                                {article.parseStatus === 'failed' ? '失败' : (article.contentReady ? '就绪' : '解析中')}
                                            </span>
                                            {article.parseStatus === 'failed' ? (
                                                <button type="button" className="nb-article-retry" onClick={(event) => { event.stopPropagation(); void handleRetryArticle(article.id); }}>重试</button>
                                            ) : null}
                                            {articleActionPendingId === article.id ? (
                                                <span className="nb-article-action-state">处理中</span>
                                            ) : null}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint"><p>暂无来源文章</p></div>
                            )}
                            {articleContextMenu ? (
                                <div
                                    ref={articleContextMenuRef}
                                    className="nb-context-menu"
                                    style={{ top: articleContextMenu.y, left: articleContextMenu.x }}
                                >
                                    <button
                                        type="button"
                                        className="nb-context-menu-item"
                                        onClick={() => openRenameArticleModal(articleContextMenu.articleId, articleContextMenu.articleTitle)}
                                    >
                                        编辑标题
                                    </button>
                                    <button
                                        type="button"
                                        className="nb-context-menu-item"
                                        onClick={() => window.open(`/notebook/${notebook.id}?articleId=${articleContextMenu.articleId}`, '_blank', 'noopener,noreferrer')}
                                    >
                                        新标签页打开
                                    </button>
                                    <button
                                        type="button"
                                        className="nb-context-menu-item"
                                        onClick={async () => {
                                            await navigator.clipboard.writeText(`${window.location.origin}/notebook/${notebook.id}?articleId=${articleContextMenu.articleId}`);
                                            setArticleContextMenu(null);
                                        }}
                                    >
                                        复制链接
                                    </button>
                                    <button
                                        type="button"
                                        className="nb-context-menu-item danger"
                                        onClick={() => openDeleteArticleModal(articleContextMenu.articleId, articleContextMenu.articleTitle)}
                                    >
                                        删除来源
                                    </button>
                                </div>
                            ) : null}
                        </div>
                    </div>
                </div>
                ) : null}

                {/* ====== CENTER COLUMN ====== */}
                <div className="nb-center">
                    {selectedArticle ? (
                        <>
                            <div className="nb-article-toolbar">
                                <div className="nb-layout-toggle-group">
                                    {[
                                        { id: 'triple', label: '三栏' },
                                        { id: 'focus', label: '双栏' },
                                        { id: 'reader', label: '阅读' },
                                    ].map((item) => (
                                        <button
                                            key={item.id}
                                            type="button"
                                            className={`nb-layout-toggle ${layoutMode === item.id ? 'active' : ''}`}
                                            onClick={() => setLayoutMode(item.id)}
                                        >
                                            {item.label}
                                        </button>
                                    ))}
                                </div>
                                <div className="nb-toolbar-left">
                                    <div className="nb-toolbar-title-row">
                                        <InlineEditableText value={selectedArticle.title} className="nb-toolbar-title-trigger" inputClassName="nb-toolbar-title-input" onSave={async (nextTitle) => { const detail = await appApi.sources.updateArticle({ notebookId: notebook.id, articleId: selectedArticle.id, title: nextTitle }); syncNotebookState(detail); }} />
                                        {selectedArticle.sourceUrl ? (
                                            <a
                                                href={selectedArticle.sourceUrl}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="nb-toolbar-source-link"
                                                title="打开链接"
                                            >
                                                {I.openLink}
                                            </a>
                                        ) : null}
                                    </div>
                                    <div className="nb-toolbar-meta">
                                        <span>{selectedArticle.author || '未知来源'}</span>
                                        <span>·</span>
                                        <span>{formatArticleDate(selectedArticle.date)}</span>
                                    </div>
                                </div>
                                <div className="nb-toolbar-right">
                                    <button
                                        className={`nb-icon-btn ${showTranslation ? 'active' : ''}`}
                                        title={articleAiBlocked ? '正文准备完成后才可翻译' : '翻译'}
                                        onClick={handleTranslate}
                                        disabled={articleAiBlocked}
                                    >
                                        {I.translate}
                                    </button>
                                    <button
                                        className={`nb-icon-btn ${showSummary ? 'active' : ''}`}
                                        title={articleAiBlocked ? '正文准备完成后才可生成摘要' : 'AI 摘要'}
                                        onClick={handleSummary}
                                        disabled={articleAiBlocked}
                                    >
                                        {I.summary}
                                    </button>
                                    <button
                                        className={`nb-icon-btn ${showAiChat ? 'active' : ''}`}
                                        title={selectedArticle && articleAiBlocked ? '正文准备完成后才可针对文章问答' : 'AI 助手'}
                                        onClick={handleToggleChat}
                                        disabled={selectedArticle ? articleAiBlocked : false}
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

                            <div className="nb-reader-toolbar">
                                <input className="input nb-reader-search-input" placeholder="文内搜索..." value={readerSearchQuery} onChange={(event) => { setReaderSearchQuery(event.target.value); setReaderSearchIndex(0); }} />
                                <span className="nb-reader-search-meta">{readerSearchMatches.length > 0 ? `${Math.min(readerSearchIndex + 1, readerSearchMatches.length)}/${readerSearchMatches.length}` : '0/0'}</span>
                                <button type="button" className="nb-icon-btn" onClick={() => setReaderSearchIndex((prev) => Math.max(prev - 1, 0))} disabled={!readerSearchMatches.length}>↑</button>
                                <button type="button" className="nb-icon-btn" onClick={() => setReaderSearchIndex((prev) => Math.min(prev + 1, readerSearchMatches.length - 1))} disabled={!readerSearchMatches.length}>↓</button>
                            </div>
                            <div className="nb-center-body" ref={centerBodyRef}>
                                <ArticleContentPane
                                    articleId={selectedArticle.id}
                                    articleFileUrl={selectedArticle.fileUrl}
                                    articleProcessingHint={selectedArticle.processingHint}
                                    articleDisplayBlocked={articleDisplayBlocked}
                                    articleRenderMode={articleRenderMode}
                                    renderedArticleContent={renderedArticleContent}
                                    fallbackToc={fallbackPdfToc}
                                    fontSize={fontSize}
                                    pageWidth={pageWidth}
                                    pdfRequestedPageNumber={pdfRequestedPageNumber}
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
                                    setPdfOutline={setPdfOutline}
                                    setPdfRequestedPageNumber={setPdfRequestedPageNumber}
                                    onCopySummary={handleCopySummary}
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

                {/* ====== RIGHT COLUMN ====== */}
                {layoutMode !== 'reader' ? (
                <div className="nb-right">
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
                                        <p className="nb-chat-welcome-hint">{chatScope === 'article' ? '已加载当前文章内容，你可以提问、讨论或请求分析' : '当前使用 notebook 级对话，可以围绕整个研究空间提问。'}</p>
                                        <div className="nb-chat-quick-actions">
                                            <button onClick={() => setChatInput('创建详细摘要')}>创建详细摘要</button>
                                            <button onClick={() => setChatScope((current) => current === 'article' ? 'notebook' : 'article')}>{chatScope === 'article' ? '切换为 notebook 对话' : '切换为文章对话'}</button>
                                        </div>
                                    </div>
                                )}
                                {chatMessages.map((msg, idx) => (
                                    <div key={msg.id || idx} className={`nb-chat-msg nb-chat-msg-${msg.role}`}>
                                        <div
                                            className={`nb-chat-bubble nb-chat-bubble-${msg.role}`}
                                            onCopy={msg.role === 'assistant' ? () => handleCopyAssistant(msg) : undefined}
                                        >
                                            {msg.role === 'assistant' && msg.route && (
                                                <div className="nb-chat-route-chip">
                                                    {msg.routeBadge || CHAT_ROUTE_LABELS[msg.route] || msg.route}
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
                                            {msg.role === 'assistant' && Array.isArray(msg.evidenceSpans) && msg.evidenceSpans.length > 0 && (
                                                <div className="nb-chat-evidence-list">
                                                    {msg.evidenceSpans.slice(0, 3).map((span, spanIndex) => (
                                                        <div
                                                            key={`${span.articleId || 'article'}-${span.chunkId || span.sectionId || spanIndex}`}
                                                            className="nb-chat-evidence-item"
                                                        >
                                                            <span className="nb-chat-evidence-label">
                                                                {span.role || span.sectionId || `证据 ${spanIndex + 1}`}
                                                            </span>
                                                            <span className="nb-chat-evidence-text">{span.text}</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                            {msg.role === 'assistant' && Array.isArray(msg.relatedArticles) && msg.relatedArticles.length > 0 && (
                                                <div className="nb-chat-citations">
                                                    {msg.relatedArticles.map((citation) => (
                                                        <button
                                                            key={`${citation.notebookId}-${citation.articleId}`}
                                                            type="button"
                                                            className="nb-chat-citation-card"
                                                            onClick={() => handleOpenCitation(citation, msg.route || 'none')}
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
                                    <textarea className="nb-chat-input nb-chat-textarea" placeholder={chatScope === 'article' ? '针对当前文章提问...' : '针对整个 notebook 提问...'} value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendChat(); } }} rows={3} />
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

                            {/* Notes Panel */}
                            <div className="nb-panel nb-right-bottom" style={{ flex: 1 }}>
                                <div className="nb-panel-header">
                                    <span className="nb-panel-icon">{I.note}</span>
                                    <span className="nb-panel-title">笔记</span>
                                    <span className="nb-panel-badge">{notes.length}</span>
                                    <button type="button" className="nb-panel-collapse" onClick={() => setLayoutMode('reader')}>收起右栏</button>
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
                ) : null}
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
            {sourceActionModal && (
                <SourceActionModal
                    mode={sourceActionModal.mode}
                    articleTitle={sourceActionModal.articleTitle}
                    nextTitle={sourceActionModal.nextTitle}
                    error={sourceActionModal.error}
                    isSubmitting={articleActionPendingId === sourceActionModal.articleId}
                    onClose={() => {
                        if (articleActionPendingId !== sourceActionModal.articleId) {
                            setSourceActionModal(null);
                        }
                    }}
                    onTitleChange={(value) => {
                        setSourceActionModal((prev) => (
                            prev ? { ...prev, nextTitle: value, error: '' } : prev
                        ));
                    }}
                    onConfirm={handleConfirmSourceAction}
                />
            )}
        </div>
    );
}
