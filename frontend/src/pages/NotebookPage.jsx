import { memo, startTransition, useState, useCallback, useRef, useEffect, useMemo, useDeferredValue } from 'react';
import { createPortal } from 'react-dom';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useTheme } from '../contexts/useTheme';
import { appApi, clearStoredSession, getStoredSession, isAuthError } from '../services/appApi';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSlug from 'rehype-slug';
import SettingsModal from '../components/SettingsModal';
import InlineEditableText from '../components/common/InlineEditableText';
import ErrorBanner from '../components/common/ErrorBanner';
import AccountMenu from '../components/common/AccountMenu';
import AddSourceModal from '../components/AddSourceModal';
import SourcePanel from '../components/SourcePanel';
import NoteModal from '../components/NoteModal';
import SourceActionModal from '../components/SourceActionModal';
import { outputLanguages } from '../data/mockData';
import './NotebookPage.css';

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

function splitMarkdownBlocks(markdown) {
    if (!markdown) return [];
    const lines = String(markdown).split('\n');
    const blocks = [];
    let buffer = [];
    let inFence = false;

    const flush = () => {
        const block = buffer.join('\n').trim();
        if (block) {
            blocks.push(block);
        }
        buffer = [];
    };

    lines.forEach((line) => {
        const trimmed = line.trim();
        if (trimmed.startsWith('```')) {
            inFence = !inFence;
            buffer.push(line);
            return;
        }
        if (!inFence && trimmed === '') {
            flush();
            return;
        }
        buffer.push(line);
    });
    flush();
    return blocks;
}

function toBlockquoteMarkdown(markdown) {
    return String(markdown || '')
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n');
}

function buildInterleavedTranslationMarkdown(originalMarkdown, translatedMarkdown) {
    const originalBlocks = splitMarkdownBlocks(originalMarkdown);
    const translatedBlocks = splitMarkdownBlocks(translatedMarkdown);
    if (!originalBlocks.length) {
        return translatedMarkdown || '';
    }

    const chunks = [];
    originalBlocks.forEach((block, index) => {
        chunks.push(block);
        const translated = translatedBlocks[index];
        if (translated) {
            chunks.push(
                `<details class="nb-translated-block">\n<summary>查看译文</summary>\n\n${toBlockquoteMarkdown(translated)}\n</details>`,
            );
        }
    });
    return chunks.join('\n\n');
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

function isEditableTarget(target) {
    const element = target instanceof HTMLElement ? target : null;
    if (!element) return false;
    const tagName = element.tagName;
    return element.isContentEditable || tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT';
}

function getArticleBodyElement(container) {
    return container?.querySelector('[data-role="article-body"]') || null;
}

function isRangeInsideRoot(range, root) {
    if (!range || !root) return false;
    const startNode = range.startContainer;
    const endNode = range.endContainer;
    return root.contains(startNode) && root.contains(endNode);
}

function buildOffsetsFromRange(root, range) {
    if (!root || !range) return { startOffset: null, endOffset: null };
    try {
        const preRange = document.createRange();
        preRange.selectNodeContents(root);
        preRange.setEnd(range.startContainer, range.startOffset);
        const startOffset = preRange.toString().length;
        const selectedText = range.toString();
        const endOffset = startOffset + selectedText.length;
        if (!Number.isFinite(startOffset) || !Number.isFinite(endOffset)) {
            return { startOffset: null, endOffset: null };
        }
        return { startOffset, endOffset };
    } catch {
        return { startOffset: null, endOffset: null };
    }
}

function countOccurrenceBeforeOffset(fullText, targetText, startOffset) {
    if (!fullText || !targetText || !Number.isFinite(startOffset)) return null;
    let occurrence = 0;
    let fromIndex = 0;
    while (true) {
        const index = fullText.indexOf(targetText, fromIndex);
        if (index < 0) break;
        if (index >= startOffset) {
            return index === startOffset ? occurrence : null;
        }
        occurrence += 1;
        fromIndex = index + targetText.length;
    }
    return null;
}

function resolveRangeByOffsets(root, startOffset, endOffset) {
    if (!root) return null;
    if (!Number.isFinite(startOffset) || !Number.isFinite(endOffset) || endOffset <= startOffset) return null;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let currentOffset = 0;
    let startNode = null;
    let endNode = null;
    let startNodeOffset = 0;
    let endNodeOffset = 0;
    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        const textLength = textNode.nodeValue?.length || 0;
        const nextOffset = currentOffset + textLength;
        if (!startNode && startOffset >= currentOffset && startOffset <= nextOffset) {
            startNode = textNode;
            startNodeOffset = Math.max(startOffset - currentOffset, 0);
        }
        if (endOffset >= currentOffset && endOffset <= nextOffset) {
            endNode = textNode;
            endNodeOffset = Math.max(endOffset - currentOffset, 0);
            break;
        }
        currentOffset = nextOffset;
    }
    if (!startNode || !endNode) return null;
    try {
        const range = document.createRange();
        range.setStart(startNode, startNodeOffset);
        range.setEnd(endNode, endNodeOffset);
        return range;
    } catch {
        return null;
    }
}

function resolveRangeByTextOccurrence(root, text, occurrenceIndex = null) {
    if (!root || !text) return null;
    const hits = collectReaderSearchMatches(root, text, 500);
    if (!hits.length) return null;
    const targetIndex = Number.isFinite(occurrenceIndex) && occurrenceIndex >= 0 && occurrenceIndex < hits.length
        ? occurrenceIndex
        : 0;
    const current = hits[targetIndex];
    if (!current?.textNode) return null;
    try {
        const range = document.createRange();
        range.setStart(current.textNode, current.start);
        range.setEnd(current.textNode, current.end);
        return range;
    } catch {
        return null;
    }
}

const HIGHLIGHT_COLOR_KEYS = ['yellow', 'blue', 'green', 'pink', 'purple', 'orange'];

function normalizeHighlightColor(color) {
    const normalized = String(color || '').trim().toLowerCase();
    return HIGHLIGHT_COLOR_KEYS.includes(normalized) ? normalized : 'yellow';
}

function resolveHighlightRange(articleBody, item) {
    if (!articleBody || !item) return null;
    let range = resolveRangeByOffsets(
        articleBody,
        Number(item.startOffset),
        Number(item.endOffset),
    );
    if (!range) {
        range = resolveRangeByTextOccurrence(
            articleBody,
            item.text || '',
            Number(item.occurrenceIndex),
        );
    }
    return range;
}

function resolveRangeAnchorRect(range) {
    if (!range) return null;
    const rects = range.getClientRects();
    if (rects?.length) {
        return rects[rects.length - 1];
    }
    const fallback = range.getBoundingClientRect();
    if (!fallback || (!fallback.width && !fallback.height)) {
        return null;
    }
    return fallback;
}

function collectReaderSearchMatches(root, query, maxHits = 200) {
    if (!root) return [];
    const keyword = query.trim();
    if (!keyword) return [];

    const lowerKeyword = keyword.toLocaleLowerCase();
    const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode(node) {
                if (!node.nodeValue?.trim()) {
                    return NodeFilter.FILTER_REJECT;
                }
                const parent = node.parentElement;
                if (!parent) {
                    return NodeFilter.FILTER_REJECT;
                }
                if (parent.closest('pre, code')) {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            },
        },
    );

    const textNodes = [];
    while (walker.nextNode()) {
        textNodes.push(walker.currentNode);
    }

    const hits = [];
    for (const textNode of textNodes) {
        if (hits.length >= maxHits) {
            break;
        }
        const rawText = textNode.nodeValue || '';
        const lowerText = rawText.toLocaleLowerCase();
        let matchIndex = lowerText.indexOf(lowerKeyword);
        while (matchIndex >= 0) {
            hits.push({
                textNode,
                start: matchIndex,
                end: matchIndex + keyword.length,
            });
            if (hits.length >= maxHits) {
                break;
            }
            matchIndex = lowerText.indexOf(lowerKeyword, matchIndex + keyword.length);
        }
    }

    return hits;
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
const GLOBAL_LAYOUT_STORAGE_KEY = 'notebook.layout.preference';
const LAYOUT_OPTIONS = [
    { id: 'triple', label: '三栏', description: '左中右' },
    { id: 'focus', label: '双栏', description: '左 + 中' },
    { id: 'reader', label: '阅读', description: '仅中栏' },
];
const LATIN_FONT_OPTIONS = [
    { id: 'times_new_roman', label: 'Times New Roman' },
    { id: 'georgia', label: 'Georgia' },
    { id: 'source_serif', label: 'Source Serif 4' },
    { id: 'source_sans', label: 'Source Sans 3' },
    { id: 'inter', label: 'Inter' },
    { id: 'jetbrains_mono', label: 'JetBrains Mono' },
];
const CJK_FONT_OPTIONS = [
    { id: 'source_han_serif', label: '思源宋体' },
    { id: 'source_han_sans', label: '思源黑体' },
    { id: 'songti', label: '宋体' },
    { id: 'kaiti', label: '楷体' },
    { id: 'yahei', label: '微软雅黑' },
];

function resolveLayoutMode(mode) {
    return LAYOUT_OPTIONS.some((item) => item.id === mode) ? mode : 'triple';
}

function getStoredLayoutMode() {
    if (typeof window === 'undefined') return 'triple';
    const stored = window.localStorage.getItem(GLOBAL_LAYOUT_STORAGE_KEY);
    return resolveLayoutMode(stored);
}

function persistLayoutMode(mode) {
    if (typeof window === 'undefined') return;
    if (!LAYOUT_OPTIONS.some((item) => item.id === mode)) return;
    window.localStorage.setItem(GLOBAL_LAYOUT_STORAGE_KEY, mode);
}

const ARTICLE_MARKDOWN_REMARK_PLUGINS = [remarkGfm];
const ARTICLE_MARKDOWN_REHYPE_PLUGINS = [rehypeRaw, rehypeSlug];

const markdownComponents = {
    p({ node, children, ...props }) {
        const hasBlockChild = Array.isArray(node?.children) && node.children.some((child) => (
            child?.tagName === 'pre'
            || (
                child?.tagName === 'code'
                && Array.isArray(child?.properties?.className)
                && child.properties.className.some((name) => String(name).startsWith('language-'))
            )
        ));
        if (hasBlockChild) {
            return <>{children}</>;
        }
        return <p {...props}>{children}</p>;
    },
    code({ inline, className, children, ...props }) {
        const codeText = String(children || '');
        const match = /language-(\w+)/.exec(className || '');
        const isInlineCode = inline ?? (!match && !codeText.includes('\n'));
        if (isInlineCode) {
            return <code className={className} {...props}>{children}</code>;
        }
        return (
            <SyntaxHighlighter
                style={oneDark}
                language={match?.[1] || 'text'}
                PreTag="pre"
                CodeTag="code"
                customStyle={{ borderRadius: '16px', margin: 0, fontSize: '0.86em' }}
                {...props}
            >
                {codeText.replace(/\n$/, '')}
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

const ArticleContentPane = memo(function ArticleContentPane({
    articleId,
    articleProcessingHint,
    articleDisplayBlocked,
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
    translationRenderMode,
    onToggleTranslationRenderMode,
    setShowSummary,
    setShowTranslation,
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
                        {!translationLoading && translationText ? (
                            <button
                                className="nb-summary-mode-btn"
                                onClick={onToggleTranslationRenderMode}
                                title={translationRenderMode === 'interleaved' ? '切换为整文译文' : '切换为逐段对照'}
                            >
                                {translationRenderMode === 'interleaved' ? '整文' : '逐段'}
                            </button>
                        ) : null}
                        <button className="nb-icon-btn-sm" onClick={() => setShowTranslation(false)}>{I.close}</button>
                    </div>
                    <div className="nb-summary-body">
                        {translationLoading ? (
                            <div className="nb-summary-loading"><span className="nb-spinner" /><span>正在生成译文...</span></div>
                        ) : translationError ? (
                            <p>{translationError}</p>
                        ) : null}
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
    notebook: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 2h9a3 3 0 0 1 3 3v14a1 1 0 0 1-1.6.8L13 17.4l-3.4 2.4A1 1 0 0 1 8 19V5a3 3 0 0 0-2-2.82V2Zm4 4h5v2h-5V6Zm0 4h5v2h-5v-2Z" /><path d="M4 3.5A1.5 1.5 0 0 1 5.5 2h.5v20h-.5A1.5 1.5 0 0 1 4 20.5v-17Z" /></svg>,
    translate: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.87 15.07l-2.54-2.51.03-.03A17.52 17.52 0 0014.07 6H17V4h-7V2H8v2H1v2h11.17C11.5 7.92 10.44 9.75 9 11.35 8.07 10.32 7.3 9.19 6.69 8h-2c.73 1.63 1.73 3.17 2.98 4.56l-5.09 5.02L4 19l5-5 3.11 3.11.76-2.04zM18.5 10h-2L12 22h2l1.12-3h4.75L21 22h2l-4.5-12zm-2.62 7l1.62-4.33L19.12 17h-3.24z" /></svg>,
    summary: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    chat: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z" /><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z" /></svg>,
    more: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z" /></svg>,
    addNote: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    highlight: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.97 4.5l3.53 3.53-8.49 8.49H7.48V13l8.49-8.5zM4 20h16v2H4z" /></svg>,
    copy: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 1H4c-1.1 0-2 .9-2 2v12h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z" /></svg>,
    comment: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M21 6h-2v9H7v2c0 .55.45 1 1 1h9l4 4V7c0-.55-.45-1-1-1zM17 12V3c0-.55-.45-1-1-1H3c-.55 0-1 .45-1 1v14l4-4h10c.55 0 1-.45 1-1z" /></svg>,
    edit: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14.06 9.02l.92.92L5.92 19H5v-.92l9.06-9.06M17.66 3c-.25 0-.51.1-.7.29l-1.83 1.83 3.75 3.75 1.83-1.83c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.2-.2-.45-.29-.71-.29zm-3.6 3.19L3 17.25V21h3.75L17.81 9.94l-3.75-3.75z" /></svg>,
    theme: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 8.69V4h-4.69L12 .69 8.69 4H4v4.69L.69 12 4 15.31V20h4.69L12 23.31 15.31 20H20v-4.69L23.31 12 20 8.69zM12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-10c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4z" /></svg>,
    layout: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 3h18v18H3V3zm2 2v14h14V5H5zm2 2h4v4H7V7zm0 6h4v4H7v-4zm6-6h4v10h-4V7z" /></svg>,
    settings: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.62-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" /></svg>,
    close: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" /></svg>,
    send: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" /></svg>,
    sparkle: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    note: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" /></svg>,
    toc: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 6h16v2H4zm0 5h16v2H4zm0 5h16v2H4z" /></svg>,
    font: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M9.93 13.5h4.14L12 7.98 9.93 13.5zM20 2H4c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-4.05 16.5l-1.14-3H9.17l-1.12 3H5.96l5.11-13h1.86l5.11 13h-2.09z" /></svg>,
    deleteChat: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" /></svg>,
    openLink: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z" /></svg>,
    search: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 1 0 16 9.5a6.43 6.43 0 0 0-1.57 4.23l.27.28h.79l5 4.99L20.49 19Zm-6 0A4.5 4.5 0 1 1 14 9.5 4.5 4.5 0 0 1 9.5 14Z" /></svg>,
    collapseLeft: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 4h18v16H3V4zm2 2v12h5V6H5zm8 6 4-4v8l-4-4z" /></svg>,
    collapseRight: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 4h18v16H3V4zm9 0v12h7V6h-7zm-1 8-4-4 4-4v8z" /></svg>,
    // Source-type icons (rendered in theme color via CSS)
    arxiv: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L14.85 9.15L22 12L14.85 14.85L12 22L9.15 14.85L2 12L9.15 9.15L12 2Z" /></svg>,
    github: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" /></svg>,
    paper: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2H18c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zM13 9V3.5L18.5 9H13z" /></svg>,
    research: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z" /></svg>,
    article: <svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" /></svg>,
};

function buildSiteFavicon(url) {
    if (!url) return '';
    try {
        const parsed = new URL(url.startsWith('http') ? url : `https://${url}`);
        if (!parsed.hostname) return '';
        return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(parsed.hostname)}&sz=64`;
    } catch {
        return '';
    }
}

function isUploadedArticle(article) {
    const inputType = String(article?.inputType || '').toLowerCase();
    return inputType === 'file_upload' || inputType === 'file' || inputType === 'upload';
}

function isPdfArticle(article) {
    if (!article) return false;
    if (isUploadedArticle(article)) return false;
    const fileMime = String(article.fileMime || '').toLowerCase();
    const title = String(article.title || '').toLowerCase();
    const fileName = String(article.fileName || '').toLowerCase();
    const sourceUrl = String(article.sourceUrl || '').toLowerCase();
    return fileMime === 'application/pdf'
        || title.endsWith('.pdf')
        || fileName.endsWith('.pdf')
        || sourceUrl.endsWith('.pdf');
}

function resolveArticleIcon(article) {
    if (isUploadedArticle(article)) {
        return { type: 'svg', value: I.article, fallback: I.article };
    }
    if (isPdfArticle(article)) {
        return { type: 'svg', value: I.paper, fallback: I.paper };
    }
    if (article?.sourceUrl) {
        const favicon = buildSiteFavicon(article.sourceUrl);
        if (favicon) {
            return { type: 'favicon', value: favicon, fallback: I.article };
        }
    }
    return { type: 'svg', value: I.article, fallback: I.article };
}

/* ============================================
   Notebook Page
   ============================================ */
export default function NotebookPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [searchParams, setSearchParams] = useSearchParams();
    const {
        toggleTheme,
        fontFamilyLatin,
        fontFamilyCjk,
        setFontFamilyLatin,
        setFontFamilyCjk,
    } = useTheme();
    const requestedArticleId = searchParams.get('articleId');

    const [currentUser, setCurrentUser] = useState(null);
    const [notebook, setNotebook] = useState(null);
    const [selectedArticle, setSelectedArticle] = useState(null);
    const [showSettings, setShowSettings] = useState(false);
    const [settingsInitialTab, setSettingsInitialTab] = useState('language');
    const [layoutMode, setLayoutMode] = useState(() => getStoredLayoutMode());
    const [showAddSource, setShowAddSource] = useState(false);
    const [isSourceDetailMode, setIsSourceDetailMode] = useState(false);
    const [pendingSourceSearch, setPendingSourceSearch] = useState(null);
    const [showAccountMenu, setShowAccountMenu] = useState(false);
    const [showArticleMenu, setShowArticleMenu] = useState(false);
    const [showLayoutPrefMenu, setShowLayoutPrefMenu] = useState(false);
    const [articleContextMenu, setArticleContextMenu] = useState(null);
    const [articleActionPendingId, setArticleActionPendingId] = useState(null);
    const [sourceActionModal, setSourceActionModal] = useState(null);
    const [renderedToc, setRenderedToc] = useState([]);
    const [isPageLoading, setIsPageLoading] = useState(true);
    const [pageError, setPageError] = useState('');
    const menuRef = useRef(null);
    const layoutPrefRef = useRef(null);
    const articleContextMenuRef = useRef(null);
    const selectionToolbarRef = useRef(null);
    const commentBubbleLayerRef = useRef(null);
    const commentPopoverRef = useRef(null);
    const centerBodyRef = useRef(null);
    const readerSearchInputRef = useRef(null);
    const readerSearchHitRefs = useRef([]);
    const chatFeedbackTimerRef = useRef(null);
    const articleReadyRefreshRef = useRef(new Set());

    // AI features
    const [showSummary, setShowSummary] = useState(false);
    const [summaryText, setSummaryText] = useState('');
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [summaryCacheByArticleId, setSummaryCacheByArticleId] = useState({});
    const [showAiChat, setShowAiChat] = useState(false);
    const [chatScope, setChatScope] = useState('article');
    const [chatSessions, setChatSessions] = useState([]);
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
    const [translationTargetLanguage, setTranslationTargetLanguage] = useState('');
    const [translationRenderMode, setTranslationRenderMode] = useState('interleaved');
    const [readerSearchQuery, setReaderSearchQuery] = useState('');
    const [readerSearchIndex, setReaderSearchIndex] = useState(0);
    const [readerSearchMatchCount, setReaderSearchMatchCount] = useState(0);
    const [readerSearchShouldJump, setReaderSearchShouldJump] = useState(false);
    const [chatFeedback, setChatFeedback] = useState('');
    const [articleHighlights, setArticleHighlights] = useState([]);
    const [highlightToolbar, setHighlightToolbar] = useState({
        visible: false,
        x: 0,
        y: 0,
        text: '',
        startOffset: null,
        endOffset: null,
        occurrenceIndex: null,
    });
    const [isPersistingHighlight, setIsPersistingHighlight] = useState(false);
    const [pendingHighlightFocusId, setPendingHighlightFocusId] = useState(null);
    const [commentBubbleAnchors, setCommentBubbleAnchors] = useState([]);
    const [activeCommentBubbleId, setActiveCommentBubbleId] = useState(null);
    const [commentComposer, setCommentComposer] = useState({ open: false, value: '' });

    // Article settings
    const [fontSize, setFontSize] = useState(1.05);
    const [pageWidth, setPageWidth] = useState(720);
    const [readingProgress, setReadingProgress] = useState(0);

    // Notes state
    const [notes, setNotes] = useState([]);
    const [noteFilterTag, setNoteFilterTag] = useState('');
    const [noteModalData, setNoteModalData] = useState(null); // null = closed, object = open
    const [noteActionMenuId, setNoteActionMenuId] = useState(null);
    const [notesFeedback, setNotesFeedback] = useState('');
    const [autoOpenedEmptyNotebookId, setAutoOpenedEmptyNotebookId] = useState(null);


    const redirectToLogin = useCallback(() => {
        clearStoredSession();
        navigate('/login', { replace: true });
    }, [navigate]);
    const noteActionMenuRef = useRef(null);
    const applyLayoutMode = useCallback((nextMode) => {
        if (!LAYOUT_OPTIONS.some((item) => item.id === nextMode)) {
            return;
        }
        setLayoutMode(nextMode);
        persistLayoutMode(nextMode);
    }, []);
    const pushChatFeedback = useCallback((message) => {
        setChatFeedback(message);
        if (chatFeedbackTimerRef.current) {
            window.clearTimeout(chatFeedbackTimerRef.current);
        }
        chatFeedbackTimerRef.current = window.setTimeout(() => {
            setChatFeedback('');
        }, 1800);
    }, []);

    const trackAiEvent = useCallback((payload) => {
        if (!notebook?.id) return;
        void appApi.ai.trackAiEvent({
            notebookId: notebook.id,
            ...payload,
        }).catch(() => {});
    }, [notebook?.id]);

    useEffect(() => () => {
        if (chatFeedbackTimerRef.current) {
            window.clearTimeout(chatFeedbackTimerRef.current);
        }
    }, []);

    useEffect(() => {
        articleReadyRefreshRef.current = new Set();
        setIsSourceDetailMode(false);
    }, [id]);

    useEffect(() => {
        let cancelled = false;
        const bootstrapTranslationLanguage = async () => {
            try {
                const current = await appApi.settings.get();
                if (cancelled) return;
                const fallbackLanguage = current.outputLanguage || '中文';
                setTranslationTargetLanguage((prev) => prev || fallbackLanguage);
            } catch {
                if (!cancelled) {
                    setTranslationTargetLanguage((prev) => prev || '中文');
                }
            }
        };
        void bootstrapTranslationLanguage();
        return () => {
            cancelled = true;
        };
    }, []);

    useEffect(() => {
        if (layoutMode !== 'triple') {
            setIsSourceDetailMode(false);
        }
    }, [layoutMode]);

    useEffect(() => {
        if (!notebook?.id) {
            setSummaryCacheByArticleId({});
            return;
        }
        let cancelled = false;
        const loadNotebookSummaries = async () => {
            try {
                const items = await appApi.ai.listNotebookSummaries({ notebookId: notebook.id });
                if (cancelled) return;
                const nextCache = {};
                (Array.isArray(items) ? items : []).forEach((item) => {
                    const articleId = String(item?.articleId || '').trim();
                    const summary = String(item?.summaryText || '').trim();
                    if (!articleId || !summary) return;
                    nextCache[articleId] = summary;
                });
                setSummaryCacheByArticleId(nextCache);
            } catch (err) {
                if (cancelled) return;
                if (isAuthError(err)) {
                    redirectToLogin();
                    return;
                }
                setSummaryCacheByArticleId({});
            }
        };
        void loadNotebookSummaries();
        return () => {
            cancelled = true;
        };
    }, [notebook?.id, redirectToLogin]);

    useEffect(() => {
        if (!selectedArticle?.id) {
            setSummaryText('');
            setSummaryLoading(false);
            setShowSummary(false);
            return;
        }
        const cachedSummary = String(summaryCacheByArticleId[selectedArticle.id] || '').trim();
        if (cachedSummary) {
            setSummaryText(cachedSummary);
            setSummaryLoading(false);
            setShowSummary(true);
            return;
        }
        setSummaryText('');
        setSummaryLoading(false);
        setShowSummary(false);
    }, [selectedArticle?.id, summaryCacheByArticleId]);

    useEffect(() => {
        if (typeof window === 'undefined') return undefined;
        const handleLayoutModeChange = (event) => {
            const nextMode = resolveLayoutMode(event?.detail?.mode);
            applyLayoutMode(nextMode);
        };
        window.addEventListener('notebook-layout-mode-changed', handleLayoutModeChange);
        return () => window.removeEventListener('notebook-layout-mode-changed', handleLayoutModeChange);
    }, [applyLayoutMode]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e) => {
            if (menuRef.current && !menuRef.current.contains(e.target)) {
                setShowArticleMenu(false);
            }
            if (layoutPrefRef.current && !layoutPrefRef.current.contains(e.target)) {
                setShowLayoutPrefMenu(false);
            }
            if (articleContextMenuRef.current && !articleContextMenuRef.current.contains(e.target)) {
                setArticleContextMenu(null);
            }
            if (noteActionMenuRef.current && !noteActionMenuRef.current.contains(e.target)) {
                setNoteActionMenuId(null);
            }
            if (selectionToolbarRef.current && !selectionToolbarRef.current.contains(e.target)) {
                setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
            }
            const clickedInCommentBubble = (
                (commentBubbleLayerRef.current && commentBubbleLayerRef.current.contains(e.target))
                || (commentPopoverRef.current && commentPopoverRef.current.contains(e.target))
            );
            if (!clickedInCommentBubble) {
                setActiveCommentBubbleId(null);
            }
        };
        const handleEscape = (event) => {
            if (event.key === 'Escape') {
                setShowArticleMenu(false);
                setShowLayoutPrefMenu(false);
                setArticleContextMenu(null);
                setNoteActionMenuId(null);
                setActiveCommentBubbleId(null);
                setCommentComposer((prev) => (prev.open ? { open: false, value: '' } : prev));
            }
        };
        document.addEventListener('mousedown', handler);
        document.addEventListener('keydown', handleEscape);
        return () => {
            document.removeEventListener('mousedown', handler);
            document.removeEventListener('keydown', handleEscape);
        };
    }, []);

    useEffect(() => {
        const handleShortcut = (event) => {
            if (isEditableTarget(event.target)) {
                return;
            }
            const lowerKey = event.key.toLowerCase();
            if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
                event.preventDefault();
                applyLayoutMode('triple');
                setShowAddSource(true);
                return;
            }
            if ((event.metaKey || event.ctrlKey) && lowerKey === 'n') {
                event.preventDefault();
                openNewNote();
                return;
            }
            if ((event.metaKey || event.ctrlKey) && lowerKey === 'f' && selectedArticle) {
                event.preventDefault();
                readerSearchInputRef.current?.focus();
                readerSearchInputRef.current?.select();
                return;
            }
            if (!event.metaKey && !event.ctrlKey && (lowerKey === 'j' || lowerKey === 'k')) {
                event.preventDefault();
                centerBodyRef.current?.scrollBy({
                    top: lowerKey === 'j' ? 140 : -140,
                    behavior: 'smooth',
                });
            }
        };
        document.addEventListener('keydown', handleShortcut);
        return () => document.removeEventListener('keydown', handleShortcut);
    }, [applyLayoutMode, selectedArticle]);

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
                const [user, detail, currentSettings] = await Promise.all([
                    appApi.auth.getCurrentUser(),
                    appApi.notebooks.getDetail(id),
                    appApi.settings.get(),
                ]);
                if (!isMounted) return;
                setCurrentUser(user);
                syncNotebookState(detail);
                const preferredLayoutMode = resolveLayoutMode(currentSettings?.layoutMode);
                setLayoutMode(preferredLayoutMode);
                persistLayoutMode(preferredLayoutMode);
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
        setShowTranslation(false);
        setTranslationText('');
        setTranslationLoading(false);
        setTranslationLanguage('');
        setTranslationError('');
        setTranslationRenderMode('interleaved');
        setChatReadingCursor({
            page: null,
            sectionId: selectedArticle?.toc?.[0]?.id || null,
            blockId: null,
        });
        setHighlightToolbar((prev) => ({ ...prev, visible: false }));
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        id,
        redirectToLogin,
        selectedArticle?.contentReady,
        selectedArticle?.id,
        selectedArticle?.parseStatus,
        syncNotebookState,
    ]);

    useEffect(() => {
        if (!id || !selectedArticle?.id || !selectedArticle?.contentReady) {
            return undefined;
        }
        if (articleReadyRefreshRef.current.has(selectedArticle.id)) {
            return undefined;
        }
        articleReadyRefreshRef.current.add(selectedArticle.id);
        const timer = window.setTimeout(async () => {
            try {
                const detail = await appApi.notebooks.getDetail(id);
                syncNotebookState(detail);
            } catch (err) {
                if (isAuthError(err)) {
                    redirectToLogin();
                }
            }
        }, 900);
        return () => window.clearTimeout(timer);
    }, [id, redirectToLogin, selectedArticle?.contentReady, selectedArticle?.id, syncNotebookState]);

    useEffect(() => {
        if (!notebook?.id || !selectedArticle?.id) {
            setArticleHighlights([]);
            return;
        }
        let cancelled = false;
        const loadHighlights = async () => {
            try {
                const items = await appApi.highlights.list({
                    notebookId: notebook.id,
                    articleId: selectedArticle.id,
                });
                if (!cancelled) {
                    setArticleHighlights(Array.isArray(items) ? items : []);
                }
            } catch (err) {
                if (cancelled) return;
                if (isAuthError(err)) {
                    redirectToLogin();
                    return;
                }
                setArticleHighlights([]);
            }
        };
        void loadHighlights();
        return () => {
            cancelled = true;
        };
    }, [notebook?.id, redirectToLogin, selectedArticle?.id]);

    const articleContentReady = selectedArticle?.contentReady ?? Boolean(selectedArticle?.content?.trim());
    const articleDisplayBlocked = Boolean(selectedArticle) && !articleContentReady;
    const showTopbarReaderSearch = Boolean(selectedArticle) && !articleDisplayBlocked;
    const articleAiBlocked = !articleContentReady;
    const isChatTemporarilyBlocked = Boolean(
        selectedArticle
        && !articleContentReady
        && selectedArticle.parseStatus !== 'failed',
    );
    const toc = renderedToc;

    useEffect(() => {
        setActiveCommentBubbleId(null);
    }, [selectedArticle?.id]);

    const strippedContent = useMemo(() => (
        selectedArticle && !articleDisplayBlocked
            ? stripFirstH1(selectedArticle.content)
            : ''
    ), [selectedArticle, articleDisplayBlocked]);
    const normalizedTranslationContent = useMemo(() => (
        translationText ? stripFirstH1(translationText) : ''
    ), [translationText]);
    const renderedArticleContent = useMemo(() => {
        if (!showTranslation || !normalizedTranslationContent) {
            return strippedContent;
        }
        if (translationRenderMode === 'interleaved') {
            return buildInterleavedTranslationMarkdown(strippedContent, normalizedTranslationContent);
        }
        return normalizedTranslationContent;
    }, [
        showTranslation,
        normalizedTranslationContent,
        strippedContent,
        translationRenderMode,
    ]);
    useEffect(() => {
        const clearCssHighlights = () => {
            if (typeof CSS === 'undefined' || !CSS.highlights) {
                return;
            }
            HIGHLIGHT_COLOR_KEYS.forEach((color) => {
                CSS.highlights.delete(`nb-hl-${color}`);
            });
        };

        const container = centerBodyRef.current;
        const articleBody = getArticleBodyElement(container);
        if (!container || !articleBody || articleDisplayBlocked || !articleHighlights.length) {
            clearCssHighlights();
            setCommentBubbleAnchors([]);
            return;
        }

        const rangesByColor = new Map(HIGHLIGHT_COLOR_KEYS.map((color) => [color, []]));
        const commentAnchors = [];

        articleHighlights.forEach((item) => {
            const range = resolveHighlightRange(articleBody, item);
            if (!range) return;
            const color = normalizeHighlightColor(item.color);
            rangesByColor.get(color)?.push(range);
            if (String(item.comment || '').trim()) {
                commentAnchors.push({
                    id: item.id,
                    color,
                    comment: String(item.comment || '').trim(),
                    range,
                });
            }
        });

        if (typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined') {
            HIGHLIGHT_COLOR_KEYS.forEach((color) => {
                const ranges = rangesByColor.get(color) || [];
                if (!ranges.length) {
                    CSS.highlights.delete(`nb-hl-${color}`);
                    return;
                }
                CSS.highlights.set(`nb-hl-${color}`, new Highlight(...ranges));
            });
        }

        const updateCommentAnchors = () => {
            const containerRect = container.getBoundingClientRect();
            const maxLeft = Math.max(container.scrollWidth - 30, 0);
            const nextAnchors = commentAnchors
                .map((item) => {
                    const anchorRect = resolveRangeAnchorRect(item.range);
                    if (!anchorRect) return null;
                    const top = anchorRect.top - containerRect.top + container.scrollTop + (anchorRect.height / 2);
                    const left = Math.min(
                        anchorRect.right - containerRect.left + container.scrollLeft + 8,
                        maxLeft,
                    );
                    const POPOVER_WIDTH = 260;
                    const POPOVER_HEIGHT = 180;
                    const viewportPadding = 12;
                    let popoverLeft = anchorRect.right + 12;
                    if (popoverLeft + POPOVER_WIDTH > window.innerWidth - viewportPadding) {
                        popoverLeft = Math.max(
                            viewportPadding,
                            window.innerWidth - POPOVER_WIDTH - viewportPadding,
                        );
                    }
                    let popoverTop = anchorRect.top + (anchorRect.height / 2) + 10;
                    if (popoverTop + POPOVER_HEIGHT > window.innerHeight - viewportPadding) {
                        popoverTop = Math.max(
                            viewportPadding,
                            window.innerHeight - POPOVER_HEIGHT - viewportPadding,
                        );
                    }
                    return {
                        id: item.id,
                        comment: item.comment,
                        color: item.color,
                        top: Math.max(top, 0),
                        left: Math.max(left, 0),
                        popoverLeft,
                        popoverTop,
                    };
                })
                .filter(Boolean);
            setCommentBubbleAnchors(nextAnchors);
            setActiveCommentBubbleId((current) => (
                current && !nextAnchors.some((item) => item.id === current) ? null : current
            ));
        };

        updateCommentAnchors();
        container.addEventListener('scroll', updateCommentAnchors);
        window.addEventListener('resize', updateCommentAnchors);
        let resizeObserver = null;
        if (typeof ResizeObserver !== 'undefined') {
            resizeObserver = new ResizeObserver(() => updateCommentAnchors());
            resizeObserver.observe(articleBody);
        }

        return () => {
            container.removeEventListener('scroll', updateCommentAnchors);
            window.removeEventListener('resize', updateCommentAnchors);
            resizeObserver?.disconnect();
        };
    }, [
        articleDisplayBlocked,
        articleHighlights,
        layoutMode,
        renderedArticleContent,
        selectedArticle?.id,
        showTranslation,
        translationText,
    ]);
    const translationLanguageOptions = useMemo(() => (
        Array.from(new Set([
            '中文',
            '简体中文',
            ...outputLanguages,
            translationTargetLanguage,
            translationLanguage,
        ].filter(Boolean)))
    ), [translationLanguage, translationTargetLanguage]);
    const layoutHasLeftRail = layoutMode === 'reader';
    const layoutHasRightRail = layoutMode !== 'triple';
    const notebookDisplayIcon = useMemo(() => {
        if (!notebook) {
            return {
                type: 'icon',
                value: I.notebook,
            };
        }
        if ((notebook.articles || []).length === 0) {
            return {
                type: 'icon',
                value: I.notebook,
            };
        }
        const emoji = String(notebook.emoji || '').trim();
        if (emoji) {
            return {
                type: 'emoji',
                value: emoji,
            };
        }
        return {
            type: 'icon',
            value: I.notebook,
        };
    }, [notebook]);
    const notebookPageStyle = useMemo(() => ({
        '--nb-reader-column-width': `${pageWidth}px`,
    }), [pageWidth]);
    const triggerReaderSearchJump = useCallback((direction = 'next') => {
        const hits = readerSearchHitRefs.current || [];
        if (!hits.length) {
            return;
        }
        setReaderSearchShouldJump(true);
        setReaderSearchIndex((prev) => {
            if (direction === 'prev') {
                return prev <= 0 ? hits.length - 1 : prev - 1;
            }
            return prev >= hits.length - 1 ? 0 : prev + 1;
        });
    }, []);
    const isTocItemActive = useCallback((tocItem) => (
        Boolean(tocItem?.id) && chatReadingCursor.sectionId === tocItem.id
    ), [chatReadingCursor.sectionId]);

    useEffect(() => {
        const articleBody = getArticleBodyElement(centerBodyRef.current);
        if (!articleBody || articleDisplayBlocked || !readerSearchQuery.trim()) {
            readerSearchHitRefs.current = [];
            setReaderSearchMatchCount(0);
            setReaderSearchShouldJump(false);
            const selection = window.getSelection();
            selection?.removeAllRanges();
            return;
        }
        const hits = collectReaderSearchMatches(articleBody, readerSearchQuery, 200);
        readerSearchHitRefs.current = hits;
        setReaderSearchMatchCount(hits.length);
        setReaderSearchIndex((prev) => (
            hits.length === 0 ? 0 : Math.min(prev, hits.length - 1)
        ));
        setReaderSearchShouldJump(false);
    }, [
        articleDisplayBlocked,
        readerSearchQuery,
        renderedArticleContent,
        selectedArticle?.id,
        showTranslation,
        translationText,
    ]);

    useEffect(() => {
        if (!readerSearchShouldJump) {
            return;
        }
        const hits = readerSearchHitRefs.current || [];
        if (!hits.length) {
            setReaderSearchShouldJump(false);
            return;
        }
        const safeIndex = Math.min(Math.max(readerSearchIndex, 0), hits.length - 1);
        if (safeIndex !== readerSearchIndex) {
            setReaderSearchIndex(safeIndex);
            return;
        }
        const current = hits[safeIndex];
        if (!current?.textNode) {
            return;
        }
        try {
            const range = document.createRange();
            range.setStart(current.textNode, current.start);
            range.setEnd(current.textNode, current.end);
            const selection = window.getSelection();
            selection?.removeAllRanges();
            selection?.addRange(range);
            const container = centerBodyRef.current;
            const rangeRect = range.getBoundingClientRect();
            if (container && rangeRect.height > 0) {
                const containerRect = container.getBoundingClientRect();
                const deltaTop = rangeRect.top - containerRect.top - (container.clientHeight * 0.3);
                container.scrollBy({
                    top: deltaTop,
                    behavior: 'smooth',
                });
            } else {
                current.textNode.parentElement?.scrollIntoView({ block: 'center', behavior: 'smooth' });
            }
        } catch {
            // ignore invalid range during fast content refresh
        } finally {
            setReaderSearchShouldJump(false);
        }
    }, [readerSearchIndex, readerSearchShouldJump]);

    const clearTextSelection = useCallback(() => {
        const selection = window.getSelection();
        selection?.removeAllRanges();
    }, []);

    const focusHighlightInReader = useCallback((highlight) => {
        const container = centerBodyRef.current;
        const articleBody = getArticleBodyElement(container);
        if (!container || !articleBody || !highlight) return;
        let range = resolveRangeByOffsets(
            articleBody,
            Number(highlight.startOffset),
            Number(highlight.endOffset),
        );
        if (!range) {
            range = resolveRangeByTextOccurrence(
                articleBody,
                highlight.text || '',
                Number(highlight.occurrenceIndex),
            );
        }
        if (!range) return;
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
        const rangeRect = range.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const nextDelta = rangeRect.top - containerRect.top - (container.clientHeight * 0.32);
        container.scrollBy({ top: nextDelta, behavior: 'smooth' });
        const targetEl = range.startContainer?.parentElement;
        targetEl?.classList.add('nb-highlight-locate-flash');
        window.setTimeout(() => targetEl?.classList.remove('nb-highlight-locate-flash'), 900);
    }, []);

    useEffect(() => {
        if (!pendingHighlightFocusId || !articleHighlights.length) return;
        const target = articleHighlights.find((item) => item.id === pendingHighlightFocusId);
        if (!target) return;
        focusHighlightInReader(target);
        setPendingHighlightFocusId(null);
    }, [articleHighlights, focusHighlightInReader, pendingHighlightFocusId]);

    useEffect(() => {
        if (articleDisplayBlocked || !selectedArticle?.id) {
            setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
            return undefined;
        }
        const syncSelectionToolbar = () => {
            const container = centerBodyRef.current;
            const articleBody = getArticleBodyElement(container);
            const selection = window.getSelection();
            if (!container || !articleBody || !selection || selection.rangeCount === 0) {
                setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
                return;
            }
            const range = selection.getRangeAt(0);
            if (range.collapsed || !isRangeInsideRoot(range, articleBody)) {
                setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
                return;
            }
            const rawText = range.toString();
            const text = rawText.trim();
            if (!text || text.length < 2) {
                setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
                return;
            }
            const rect = range.getBoundingClientRect();
            if (!rect || !Number.isFinite(rect.top)) {
                setHighlightToolbar((prev) => (prev.visible ? { ...prev, visible: false } : prev));
                return;
            }
            const { startOffset, endOffset } = buildOffsetsFromRange(articleBody, range);
            const occurrenceIndex = countOccurrenceBeforeOffset(
                articleBody.textContent || '',
                rawText,
                Number(startOffset),
            );
            setHighlightToolbar({
                visible: true,
                x: rect.left + (rect.width / 2),
                y: Math.max(rect.top - 14, 24),
                text: rawText,
                startOffset,
                endOffset,
                occurrenceIndex,
            });
        };
        document.addEventListener('mouseup', syncSelectionToolbar);
        document.addEventListener('keyup', syncSelectionToolbar);
        return () => {
            document.removeEventListener('mouseup', syncSelectionToolbar);
            document.removeEventListener('keyup', syncSelectionToolbar);
        };
    }, [articleDisplayBlocked, selectedArticle?.id]);

    const createHighlightFromToolbar = useCallback(async ({ color = 'yellow', comment = '', openNote = false }) => {
        if (!notebook?.id || !selectedArticle?.id) return null;
        const text = (highlightToolbar.text || '').trim();
        if (!text) return null;
        if (openNote) {
            const sourceMarker = `notebook://article/${selectedArticle.id}`;
            const quoteText = text.replace(/\s+/g, ' ').trim();
            setNoteModalData({
                title: `${selectedArticle.title} 选段笔记`,
                type: '笔记',
                sources: 1,
                tags: ['高亮摘录'],
                content: `> ${quoteText}\n>\n> [来源：${selectedArticle.title}](${sourceMarker})\n`,
                time: '刚刚',
            });
            setHighlightToolbar((prev) => ({ ...prev, visible: false }));
            clearTextSelection();
            return null;
        }

        setIsPersistingHighlight(true);
        try {
            const item = await appApi.highlights.create({
                notebookId: notebook.id,
                articleId: selectedArticle.id,
                text,
                color,
                comment,
                startOffset: Number.isFinite(highlightToolbar.startOffset) ? highlightToolbar.startOffset : null,
                endOffset: Number.isFinite(highlightToolbar.endOffset) ? highlightToolbar.endOffset : null,
                occurrenceIndex: Number.isFinite(highlightToolbar.occurrenceIndex) ? highlightToolbar.occurrenceIndex : null,
            });
            setArticleHighlights((prev) => [item, ...prev.filter((existing) => existing.id !== item.id)]);
            setHighlightToolbar((prev) => ({ ...prev, visible: false }));
            clearTextSelection();
            return item;
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return null;
            }
            pushChatFeedback(err.message || '保存高亮失败');
            return null;
        } finally {
            setIsPersistingHighlight(false);
        }
    }, [
        clearTextSelection,
        highlightToolbar.endOffset,
        highlightToolbar.occurrenceIndex,
        highlightToolbar.startOffset,
        highlightToolbar.text,
        notebook?.id,
        pushChatFeedback,
        redirectToLogin,
        selectedArticle?.id,
        selectedArticle?.title,
    ]);

    const openCommentComposer = useCallback(() => {
        setCommentComposer({ open: true, value: '' });
        setHighlightToolbar((prev) => ({ ...prev, visible: false }));
    }, []);

    const closeCommentComposer = useCallback(() => {
        setCommentComposer({ open: false, value: '' });
    }, []);

    const submitCommentComposer = useCallback(async () => {
        const comment = String(commentComposer.value || '').trim();
        await createHighlightFromToolbar({ color: 'yellow', comment });
        setCommentComposer({ open: false, value: '' });
    }, [commentComposer.value, createHighlightFromToolbar]);

    const handleDeleteHighlight = useCallback(async (highlightId) => {
        if (!notebook?.id || !selectedArticle?.id || !highlightId) return;
        setIsPersistingHighlight(true);
        try {
            await appApi.highlights.remove({
                notebookId: notebook.id,
                articleId: selectedArticle.id,
                highlightId,
            });
            setArticleHighlights((prev) => prev.filter((item) => item.id !== highlightId));
            setActiveCommentBubbleId((current) => (current === highlightId ? null : current));
            pushChatFeedback('已删除高亮/批注');
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            pushChatFeedback(err.message || '删除高亮失败');
        } finally {
            setIsPersistingHighlight(false);
        }
    }, [notebook?.id, pushChatFeedback, redirectToLogin, selectedArticle?.id]);

    const handleDeleteHighlightFromSelection = useCallback(async () => {
        if (!notebook?.id || !selectedArticle?.id) return;
        const start = Number(highlightToolbar.startOffset);
        const end = Number(highlightToolbar.endOffset);
        let matched = [];

        if (Number.isFinite(start) && Number.isFinite(end) && end > start) {
            matched = articleHighlights.filter((item) => {
                const itemStart = Number(item.startOffset);
                const itemEnd = Number(item.endOffset);
                if (Number.isFinite(itemStart) && Number.isFinite(itemEnd) && itemEnd > itemStart) {
                    return Math.max(start, itemStart) < Math.min(end, itemEnd);
                }
                return false;
            });
        }

        if (!matched.length) {
            const selectedText = (highlightToolbar.text || '').trim();
            if (selectedText) {
                matched = articleHighlights.filter((item) => (item.text || '').trim() === selectedText);
            }
        }

        if (!matched.length) {
            pushChatFeedback('当前选区没有可删除的高亮');
            return;
        }

        setIsPersistingHighlight(true);
        try {
            for (const item of matched) {
                await appApi.highlights.remove({
                    notebookId: notebook.id,
                    articleId: selectedArticle.id,
                    highlightId: item.id,
                });
            }
            const removedIds = new Set(matched.map((item) => item.id));
            setArticleHighlights((prev) => prev.filter((item) => !removedIds.has(item.id)));
            setActiveCommentBubbleId((current) => (current && removedIds.has(current) ? null : current));
            setHighlightToolbar((prev) => ({ ...prev, visible: false }));
            clearTextSelection();
            pushChatFeedback(`已删除 ${matched.length} 条高亮/批注`);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            pushChatFeedback(err.message || '删除高亮失败');
        } finally {
            setIsPersistingHighlight(false);
        }
    }, [
        articleHighlights,
        clearTextSelection,
        highlightToolbar.endOffset,
        highlightToolbar.startOffset,
        highlightToolbar.text,
        notebook?.id,
        pushChatFeedback,
        redirectToLogin,
        selectedArticle?.id,
    ]);

    // AI Summary
    const handleSummary = async () => {
        if (showSummary) { setShowSummary(false); return; }
        if (!notebook || !selectedArticle) return;
        const articleId = selectedArticle.id;
        setShowSummary(true);
        const cachedSummary = String(summaryCacheByArticleId[articleId] || summaryText || '').trim();
        if (cachedSummary) {
            setSummaryText(cachedSummary);
            setSummaryLoading(false);
            return;
        }
        setSummaryLoading(true);
        setSummaryText('');
        try {
            let streamedText = '';
            const result = await appApi.ai.streamSummary({
                notebookId: notebook.id,
                articleId,
                onToken: (token) => {
                    const chunk = String(token || '');
                    if (!chunk) return;
                    streamedText += chunk;
                    setSummaryText((prev) => `${prev}${chunk}`);
                },
            });
            const finalSummary = String(result?.summaryText || streamedText).trim();
            if (finalSummary) {
                setSummaryText(finalSummary);
                setSummaryCacheByArticleId((prev) => ({ ...prev, [articleId]: finalSummary }));
            } else {
                setSummaryText('摘要生成结果为空，请重试。');
            }
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setSummaryText(err?.message || '摘要生成失败，请重试。');
        } finally {
            setSummaryLoading(false);
        }
    };

    const requestTranslation = useCallback(async (preferredLanguage) => {
        if (!notebook || !selectedArticle) return;
        const targetLanguage = (preferredLanguage || translationTargetLanguage || '中文').trim() || '中文';
        setTranslationLanguage(targetLanguage);
        setTranslationTargetLanguage(targetLanguage);
        setTranslationLoading(true);
        setTranslationText('');
        setTranslationError('');
        try {
            const result = await appApi.ai.translateArticle({
                notebookId: notebook.id,
                articleId: selectedArticle.id,
                targetLanguage,
            });
            setTranslationText(result.translatedContent || '');
            setTranslationLanguage(result.targetLanguage || targetLanguage);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setTranslationError(err.message || '翻译失败');
        } finally {
            setTranslationLoading(false);
        }
    }, [notebook, redirectToLogin, selectedArticle, translationTargetLanguage]);

    const handleTranslate = async () => {
        if (showTranslation) {
            setShowTranslation(false);
            return;
        }
        if (!notebook || !selectedArticle) return;

        setShowTranslation(true);
        await requestTranslation(translationTargetLanguage || translationLanguage || '中文');
    };

    const handleTranslationLanguageChange = async (nextLanguage) => {
        setTranslationTargetLanguage(nextLanguage);
        if (showTranslation) {
            await requestTranslation(nextLanguage);
        }
    };

    const handleToggleChat = async () => {
        const nextValue = !showAiChat;
        setShowAiChat(nextValue);
        if (nextValue) {
            applyLayoutMode('triple');
            if (isChatTemporarilyBlocked) {
                pushChatFeedback('正文解析中，助手暂不可提问');
            } else {
                pushChatFeedback('已打开 AI 助手');
            }
            if (!selectedArticle) setChatScope('notebook');
            try {
                const sessions = await appApi.settings.listConversations({ notebookId: notebook.id });
                setChatSessions(sessions);
            } catch (error) {
                console.error('chat.sessions_load_failed', error);
            }
        }
    };

    const handleSendChat = async () => {
        if (!chatInput.trim() || !notebook || isChatStreaming || isChatTemporarilyBlocked) return;
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
        const recentHighlights = articleHighlights
            .slice(0, 8)
            .map((item) => ({
                id: item.id,
                articleId: item.articleId || selectedArticle?.id || null,
                text: item.text || '',
                comment: item.comment || '',
                color: item.color || 'yellow',
            }))
            .filter((item) => item.text.trim());
        try {
            const result = await appApi.ai.streamAssistant({
                notebookId: notebook.id,
                articleId: chatScope === 'article' ? selectedArticle?.id : null,
                conversationId: chatConversationId,
                message: prompt,
                readingCursor: chatReadingCursor,
                recentHighlights,
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
            setChatSessions((prev) => {
                const nextSessionId = result.conversationId || chatConversationId;
                if (!nextSessionId) return prev;
                const existing = prev.find((item) => item.id === nextSessionId);
                const nextSession = { id: nextSessionId, title: prompt.slice(0, 24), messages: [] };
                return existing ? prev : [nextSession, ...prev];
            });
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
    }, []);

    useEffect(() => {
        if (!selectedArticle || articleDisplayBlocked) {
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
            const maxScroll = Math.max(container.scrollHeight - container.clientHeight, 1);
            setReadingProgress(Math.round((container.scrollTop / maxScroll) * 100));
        };
        container.addEventListener('scroll', syncScrollSpy);
        syncScrollSpy();

        return () => {
            window.cancelAnimationFrame(frameId);
            container.removeEventListener('scroll', syncScrollSpy);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        articleDisplayBlocked,
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
        if (citation.sourceType === 'web') {
            parts.push('网络来源');
        }
        return parts.join(' · ');
    }, []);

    const buildChatCitationItems = useCallback((message) => {
        const rows = [];
        const seen = new Set();
        const related = Array.isArray(message?.relatedArticles) ? message.relatedArticles : [];
        related.forEach((citation, index) => {
            const key = citation.articleId
                || citation.url
                || `${citation.title || 'citation'}-${citation.index || index}`;
            if (seen.has(key)) return;
            seen.add(key);
            rows.push({
                ...citation,
                citationLabel: citation.citationLabel || `[${citation.index || index + 1}]`,
                title: citation.title || '未命名来源',
                core: citation.snippet || '',
                reason: citation.whySimilar || '',
            });
        });
        if (rows.length > 0) {
            return rows;
        }
        const spans = Array.isArray(message?.evidenceSpans) ? message.evidenceSpans : [];
        return spans.slice(0, 6).map((span, index) => ({
            citationLabel: `[${span.index || index + 1}]`,
            title: span.role || span.sectionId || '证据片段',
            core: span.text || '',
            reason: '',
            articleId: span.articleId || null,
            notebookId: notebook?.id || null,
            sourceType: 'local',
        }));
    }, [notebook?.id]);

    const handleOpenCitation = useCallback((citation, route = 'none') => {
        if (citation?.url && !citation?.articleId) {
            window.open(citation.url, '_blank', 'noopener,noreferrer');
            return;
        }
        const targetNotebookId = citation?.notebookId || notebook?.id;
        if (!targetNotebookId || !citation?.articleId) return;
        trackAiEvent({
            operation: 'chat',
            action: 'citation_open',
            route,
            articleId: citation.articleId,
            conversationId: chatConversationId,
        });
        if (targetNotebookId === notebook?.id) {
            const article = notebook.articles.find((item) => item.id === citation.articleId);
            if (article) {
                handleSelectArticle(article);
                pushChatFeedback(`已跳转：${article.title}`);
            }
            return;
        }
        navigate(`/notebook/${targetNotebookId}?articleId=${citation.articleId}`);
    }, [chatConversationId, handleSelectArticle, navigate, notebook, pushChatFeedback, trackAiEvent]);

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
        pushChatFeedback('已清空当前会话');
    };

    const handleSwitchConversation = useCallback((session) => {
        setChatConversationId(session.id);
        setChatMessages((session.messages || []).map((message, index) => ({
            id: `${session.id}-${index}`,
            role: message.role,
            content: message.content || '',
            route: message.route || null,
            routeBadge: message.routeBadge || '',
            relatedArticles: [],
            evidenceSpans: [],
            isStreaming: false,
        })));
        pushChatFeedback(`已切换到：${session.title}`);
    }, [pushChatFeedback]);

    const handleDeleteConversation = useCallback(async (session) => {
        if (!notebook?.id) return;
        try {
            await appApi.settings.deleteConversation({ notebookId: notebook.id, conversationId: session.id });
            setChatSessions((prev) => prev.filter((item) => item.id !== session.id));
            if (chatConversationId === session.id) {
                setChatConversationId(null);
                setChatMessages([]);
            }
            pushChatFeedback('会话已删除');
        } catch (err) {
            pushChatFeedback(err?.message || '删除会话失败');
        }
    }, [chatConversationId, notebook?.id, pushChatFeedback]);

    const handleLogout = useCallback(async () => {
        await appApi.auth.logout();
        redirectToLogin();
    }, [redirectToLogin]);

    const handleOpenNoteSourceMarker = useCallback((marker) => {
        const articleId = marker?.articleId;
        if (!articleId || !notebook) return;
        const article = notebook.articles.find((item) => item.id === articleId);
        if (!article) return;
        handleSelectArticle(article);
        if (marker?.highlightId) {
            setPendingHighlightFocusId(marker.highlightId);
        }
        setNoteModalData(null);
    }, [handleSelectArticle, notebook]);

    const handleExportNotebook = useCallback(async () => {
        if (!notebook?.id) return;
        try {
            const { blob, filename } = await appApi.notebooks.exportNotebook(notebook.id);
            const link = document.createElement('a');
            const blobUrl = URL.createObjectURL(blob);
            link.href = blobUrl;
            link.download = filename || 'notebook.md';
            link.click();
            URL.revokeObjectURL(blobUrl);
            setNotesFeedback('');
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            setNotesFeedback(err.message || '导出笔记本失败');
        }
    }, [notebook?.id, redirectToLogin]);

    // Note handlers – use modal
    const openNewNote = () => {
        const newNote = { title: '', content: '', type: '笔记', sources: 0, time: '刚刚' };
        setNoteModalData(newNote);
    };

    const openExistingNote = (note) => {
        setNoteModalData(note);
    };

    const exportNote = async (noteId) => {
        if (!notebook) return;
        try {
            setNotesFeedback('');
            const { blob, filename } = await appApi.notes.exportNote(notebook.id, noteId);
            const link = document.createElement('a');
            const blobUrl = URL.createObjectURL(blob);
            link.href = blobUrl;
            link.download = filename || 'note.md';
            link.click();
            URL.revokeObjectURL(blobUrl);
        } catch (err) {
            setNotesFeedback(err.message || '导出失败，请稍后重试');
        }
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
        setNoteActionMenuId((current) => (current === noteId ? null : current));
        if (noteModalData?.id === noteId) {
            setNoteModalData(null);
        }
    };

    const handleSourcesImported = useCallback((detail) => {
        syncNotebookState(detail);
        setIsSourceDetailMode(false);
    }, [syncNotebookState]);

    const handleStartSourceSearch = useCallback(({ query, mode }) => {
        applyLayoutMode('triple');
        setPendingSourceSearch({
            query,
            mode,
            requestId: Date.now(),
        });
    }, [applyLayoutMode]);

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
        if (!notebook?.id) {
            return;
        }
        if (notebook.articles.length === 0 && autoOpenedEmptyNotebookId !== notebook.id) {
            setShowAddSource(true);
            setAutoOpenedEmptyNotebookId(notebook.id);
        }
    }, [autoOpenedEmptyNotebookId, notebook?.articles.length, notebook?.id]);

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
        <div className="notebook-page" style={notebookPageStyle}>
            {/* Top Bar */}
            <header
                className="nb-topbar"
                data-layout={layoutMode}
                data-left-rail={layoutHasLeftRail ? 'true' : 'false'}
                data-right-rail={layoutHasRightRail ? 'true' : 'false'}
            >
                <div className="nb-topbar-left">
                    <button className="nb-icon-btn" onClick={() => navigate('/home')} title="返回">{I.back}</button>
                    <div className="nb-topbar-title">
                        <span className={`nb-topbar-emoji ${notebookDisplayIcon.type === 'emoji' ? 'emoji' : 'icon'}`}>
                            {notebookDisplayIcon.value}
                        </span>
                        <InlineEditableText
                            value={notebook.title}
                            className="nb-topbar-title-trigger"
                            inputClassName="nb-topbar-title-input"
                            showEditIcon={false}
                            onSave={handleRenameNotebook}
                        />
                    </div>
                </div>
                <div className="nb-topbar-center">
                    {showTopbarReaderSearch ? (
                        <div className="nb-topbar-reader-search">
                            <input
                                ref={readerSearchInputRef}
                                className="nb-topbar-reader-search-input"
                                placeholder="文内搜索..."
                                value={readerSearchQuery}
                                onChange={(event) => {
                                    setReaderSearchQuery(event.target.value);
                                    setReaderSearchIndex(0);
                                    setReaderSearchShouldJump(false);
                                }}
                                onKeyDown={(event) => {
                                    if (event.key === 'Enter') {
                                        event.preventDefault();
                                        triggerReaderSearchJump(event.shiftKey ? 'prev' : 'next');
                                    }
                                }}
                            />
                            <span className="nb-topbar-reader-search-meta">{readerSearchMatchCount > 0 ? `${Math.min(readerSearchIndex + 1, readerSearchMatchCount)}/${readerSearchMatchCount}` : '0/0'}</span>
                            <button type="button" className="nb-icon-btn-sm" onClick={() => triggerReaderSearchJump('prev')} disabled={!readerSearchMatchCount}>↑</button>
                            <button type="button" className="nb-icon-btn-sm" onClick={() => triggerReaderSearchJump('next')} disabled={!readerSearchMatchCount}>↓</button>
                        </div>
                    ) : null}
                </div>
                <div className="nb-topbar-right">
                    <button
                        className={`nb-icon-btn ${showAiChat ? 'active' : ''}`}
                        onClick={handleToggleChat}
                        title={isChatTemporarilyBlocked ? '正文解析中，助手暂不可提问' : 'AI 助手'}
                    >
                        {I.chat}
                    </button>
                    <div className="nb-layout-pref-wrapper" ref={layoutPrefRef}>
                        <button
                            className={`nb-icon-btn ${showLayoutPrefMenu ? 'active' : ''}`}
                            onClick={() => setShowLayoutPrefMenu((current) => !current)}
                            title="页面布局"
                        >
                            {I.layout}
                        </button>
                        {showLayoutPrefMenu ? (
                            <div className="nb-layout-pref-menu">
                                {LAYOUT_OPTIONS.map((option) => (
                                    <button
                                        key={option.id}
                                        type="button"
                                        className={`nb-layout-pref-item ${layoutMode === option.id ? 'active' : ''}`}
                                        onClick={() => {
                                            applyLayoutMode(option.id);
                                            setShowLayoutPrefMenu(false);
                                        }}
                                    >
                                        <span className="nb-layout-pref-label">{option.label}</span>
                                        <span className="nb-layout-pref-desc">{option.description}</span>
                                    </button>
                                ))}
                            </div>
                        ) : null}
                    </div>
                    <button className="nb-icon-btn" onClick={toggleTheme} title="切换主题">{I.theme}</button>
                    <button
                        className="nb-icon-btn"
                        onClick={() => {
                            setSettingsInitialTab('language');
                            setShowSettings(true);
                        }}
                        title="设置"
                    >
                        {I.settings}
                    </button>
                    <div className="nb-account-wrapper">
                        <button type="button" className="nb-avatar-btn" onClick={() => setShowAccountMenu((current) => !current)}>
                            <div className="nb-avatar">
                                {(currentUser?.avatar || getStoredSession()?.user?.avatar) ? (
                                    <img
                                        className="nb-avatar-image"
                                        src={currentUser?.avatar || getStoredSession()?.user?.avatar}
                                        alt={currentUser?.name || getStoredSession()?.user?.name || '用户头像'}
                                    />
                                ) : (
                                    currentUser?.name?.charAt(0) || getStoredSession()?.user?.name?.charAt(0) || 'U'
                                )}
                            </div>
                        </button>
                        <AccountMenu
                            open={showAccountMenu}
                            user={currentUser || getStoredSession()?.user}
                            onClose={() => setShowAccountMenu(false)}
                            onOpenSettings={() => {
                                setShowAccountMenu(false);
                                setSettingsInitialTab('account');
                                setShowSettings(true);
                            }}
                            onLogout={handleLogout}
                        />
                    </div>
                </div>
            </header>

            {/* Main Layout */}
            <div
                className="nb-layout"
                data-layout={layoutMode}
                data-left-rail={layoutHasLeftRail ? 'true' : 'false'}
                data-right-rail={layoutHasRightRail ? 'true' : 'false'}
            >
                {layoutHasLeftRail ? (
                    <div className="nb-collapsed-rail nb-collapsed-rail-left">
                        <button type="button" className="nb-collapsed-rail-btn" onClick={() => applyLayoutMode('focus')} title="展开左栏">
                            {I.collapseLeft}
                        </button>
                    </div>
                ) : null}
                {/* ====== LEFT COLUMN ====== */}
                {layoutMode !== 'reader' ? (
                <div className="nb-left">
                    <div className="nb-panel nb-left-top">
                        <div className="nb-panel-header">
                            <span className="nb-panel-icon">{I.toc}</span>
                            <span className="nb-panel-title">文章目录</span>
                            <button type="button" className="nb-panel-collapse-icon" onClick={() => applyLayoutMode('reader')} title="收起左栏">
                                {I.collapseLeft}
                            </button>
                        </div>
                        <div className="nb-panel-body nb-list-panel-body">
                            {toc.length > 0 ? (
                                <ul className="nb-toc-list nb-list-scroll">
                                    {toc.map((item, idx) => (
                                        <li
                                            key={`${item.id || item.title}-${item.matchIndex || 0}-${idx}`}
                                            className={`nb-toc-item nb-toc-level-${item.level} ${isTocItemActive(item) ? 'active' : ''}`}
                                        >
                                            <a href={`#${item.id}`} onClick={(event) => handleTocClick(event, item)}>{item.title}</a>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint"><p>选择一篇文章查看目录</p></div>
                            )}
                        </div>
                    </div>

                    <div className="nb-panel nb-left-bottom">
                        <div className="nb-panel-header">
                            <span className="nb-panel-icon">{I.paper}</span>
                            <span className="nb-panel-title">来源文章</span>
                            <span className="nb-panel-badge">{notebook.articles.length}</span>
                        </div>
                        <div className="nb-panel-body nb-list-panel-body">
                            {notebook.articles.length > 0 ? (
                                <ul className="nb-article-list nb-list-scroll">
                                    {notebook.articles.map(article => {
                                        const articleIcon = resolveArticleIcon(article);
                                        return (
                                            <li
                                                key={article.id}
                                                className={`nb-article-item ${selectedArticle?.id === article.id ? 'active' : ''}`}
                                                onClick={() => handleSelectArticle(article)}
                                                onContextMenu={(event) => handleOpenArticleContextMenu(event, article)}
                                                title="右键可编辑或删除来源"
                                            >
                                                {articleIcon.type === 'favicon' ? (
                                                    <span className="nb-article-icon-wrap">
                                                        <img
                                                            className="nb-article-favicon"
                                                            src={articleIcon.value}
                                                            alt=""
                                                            loading="lazy"
                                                            onError={(event) => {
                                                                event.currentTarget.style.display = 'none';
                                                                const fallback = event.currentTarget.parentElement?.querySelector('.nb-article-icon-fallback');
                                                                if (fallback) fallback.style.display = 'inline-flex';
                                                            }}
                                                        />
                                                        <span className="nb-article-icon nb-article-icon-fallback">{articleIcon.fallback || I.article}</span>
                                                    </span>
                                                ) : (
                                                    <span className="nb-article-icon">{articleIcon.value}</span>
                                                )}
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
                                        );
                                    })}
                                </ul>
                            ) : (
                                <div className="nb-empty-hint" />
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
                                <div className="nb-toolbar-left">
                                    <div className="nb-toolbar-title-row">
                                        <InlineEditableText value={selectedArticle.title} className="nb-toolbar-title-trigger" inputClassName="nb-toolbar-title-input" showEditIcon={false} onSave={async (nextTitle) => { const detail = await appApi.sources.updateArticle({ notebookId: notebook.id, articleId: selectedArticle.id, title: nextTitle }); syncNotebookState(detail); }} />
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
                                    <div className="nb-translate-control">
                                        <button
                                            className={`nb-icon-btn ${showTranslation ? 'active' : ''}`}
                                            title={articleAiBlocked ? '正文准备完成后才可翻译' : '翻译'}
                                            onClick={handleTranslate}
                                            disabled={articleAiBlocked}
                                        >
                                            {I.translate}
                                        </button>
                                        <div className="nb-translate-lang-wrap">
                                            <select
                                                className="nb-translate-lang-select"
                                                title="翻译目标语言"
                                                value={translationTargetLanguage || translationLanguage || '中文'}
                                                onChange={(event) => {
                                                    void handleTranslationLanguageChange(event.target.value);
                                                }}
                                                disabled={articleAiBlocked || translationLoading}
                                            >
                                                {translationLanguageOptions.map((lang) => (
                                                    <option key={lang} value={lang}>{lang}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
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
                                        title={isChatTemporarilyBlocked ? '正文解析中，助手暂不可提问' : 'AI 助手'}
                                        onClick={handleToggleChat}
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
                                                    <label className="nb-dropdown-label">英文字体</label>
                                                    <div className="nb-dropdown-select-wrap">
                                                        <select
                                                            className="nb-dropdown-select"
                                                            value={fontFamilyLatin}
                                                            onChange={(event) => setFontFamilyLatin(event.target.value)}
                                                        >
                                                            {LATIN_FONT_OPTIONS.map((option) => (
                                                                <option key={option.id} value={option.id}>{option.label}</option>
                                                            ))}
                                                        </select>
                                                    </div>
                                                </div>
                                                <div className="nb-dropdown-section">
                                                    <label className="nb-dropdown-label">中文字体</label>
                                                    <div className="nb-dropdown-select-wrap">
                                                        <select
                                                            className="nb-dropdown-select"
                                                            value={fontFamilyCjk}
                                                            onChange={(event) => setFontFamilyCjk(event.target.value)}
                                                        >
                                                            {CJK_FONT_OPTIONS.map((option) => (
                                                                <option key={option.id} value={option.id}>{option.label}</option>
                                                            ))}
                                                        </select>
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

                            <div className="nb-reading-progress"><div className="nb-reading-progress-bar" style={{ width: `${readingProgress}%` }} /></div>
                            <div className="nb-center-body" ref={centerBodyRef}>
                                <ArticleContentPane
                                    articleId={selectedArticle.id}
                                    articleProcessingHint={selectedArticle.processingHint}
                                    articleDisplayBlocked={articleDisplayBlocked}
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
                                    translationRenderMode={translationRenderMode}
                                    onToggleTranslationRenderMode={() => setTranslationRenderMode((prev) => (prev === 'interleaved' ? 'full' : 'interleaved'))}
                                    setShowSummary={setShowSummary}
                                    setShowTranslation={setShowTranslation}
                                    onCopySummary={handleCopySummary}
                                />
                                {!articleDisplayBlocked && commentBubbleAnchors.length > 0 ? (
                                    <div className="nb-comment-bubble-layer" ref={commentBubbleLayerRef}>
                                        {commentBubbleAnchors.map((item) => (
                                            <div
                                                key={item.id}
                                                className="nb-comment-bubble-anchor"
                                                style={{ top: `${item.top}px`, left: `${item.left}px` }}
                                            >
                                                <button
                                                    type="button"
                                                    className={`nb-comment-bubble-btn ${item.color}`}
                                                    onClick={() => {
                                                        setActiveCommentBubbleId((current) => (current === item.id ? null : item.id));
                                                    }}
                                                    title="查看批注"
                                                >
                                                    💬
                                                </button>
                                                {activeCommentBubbleId === item.id && typeof document !== 'undefined'
                                                    ? createPortal(
                                                        <div
                                                            ref={commentPopoverRef}
                                                            className="nb-comment-bubble-popover"
                                                            style={{ top: `${item.popoverTop}px`, left: `${item.popoverLeft}px` }}
                                                        >
                                                            <p>{item.comment}</p>
                                                            <button
                                                                type="button"
                                                                className="nb-comment-popover-delete"
                                                                disabled={isPersistingHighlight}
                                                                onClick={(event) => {
                                                                    event.stopPropagation();
                                                                    void handleDeleteHighlight(item.id);
                                                                }}
                                                            >
                                                                删除批注
                                                            </button>
                                                        </div>,
                                                        document.body,
                                                    )
                                                    : null}
                                            </div>
                                        ))}
                                    </div>
                                ) : null}
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
                {layoutMode === 'triple' ? (
                <div className="nb-right">
                    {showAiChat ? (
                        <div className={`nb-panel nb-right-full nb-chat-panel ${isChatTemporarilyBlocked ? 'blocked' : ''}`}>
                            <div className="nb-panel-header nb-chat-header">
                                <span className="nb-panel-title">AI 助手</span>
                                <div className="nb-chat-header-actions">
                                    <button className="nb-icon-btn-sm" onClick={clearChat} title="清空对话">{I.deleteChat}</button>
                                    <button className="nb-icon-btn-sm" onClick={() => setShowAiChat(false)} title="关闭">{I.close}</button>
                                </div>
                            </div>
                            {isChatTemporarilyBlocked ? (
                                <div className="nb-chat-blocking-banner">正文解析中，助手暂不可提问</div>
                            ) : null}
                            <div className="nb-chat-sessions">
                                <button
                                    type="button"
                                    className="nb-chat-session-new"
                                    onClick={() => {
                                        setChatConversationId(null);
                                        setChatMessages([]);
                                        pushChatFeedback('已创建空白对话');
                                    }}
                                >
                                    新建对话
                                </button>
                                {chatFeedback ? <p className="nb-chat-feedback">{chatFeedback}</p> : null}
                                {chatSessions.map((session) => (
                                    <div key={session.id} className={`nb-chat-session-item ${chatConversationId === session.id ? 'active' : ''}`}>
                                        <button type="button" className="nb-chat-session-switch" onClick={() => handleSwitchConversation(session)}>
                                            {session.title}
                                        </button>
                                        <button type="button" className="nb-chat-session-delete" onClick={() => { void handleDeleteConversation(session); }}>✕</button>
                                    </div>
                                ))}
                            </div>
                            <div className="nb-chat-messages">
                                {chatMessages.length === 0 && (
                                    <div className="nb-chat-welcome">
                                        <div className="nb-chat-welcome-icon">{I.sparkle}</div>
                                        <p className="nb-chat-welcome-title">有什么想问的?</p>
                                        <p className="nb-chat-welcome-hint">
                                            {isChatTemporarilyBlocked
                                                ? '等待当前文章解析完成后即可提问'
                                                : (chatScope === 'article' ? '围绕当前文章提问' : '围绕整个 notebook 提问')}
                                        </p>
                                        <div className="nb-chat-quick-actions">
                                            <button disabled={isChatTemporarilyBlocked} onClick={() => setChatInput('创建详细摘要')}>创建详细摘要</button>
                                            <button disabled={isChatTemporarilyBlocked} onClick={() => setChatScope((current) => current === 'article' ? 'notebook' : 'article')}>{chatScope === 'article' ? '切换为 notebook 对话' : '切换为文章对话'}</button>
                                        </div>
                                    </div>
                                )}
                                {chatMessages.map((msg, idx) => {
                                    const citationItems = msg.role === 'assistant' ? buildChatCitationItems(msg) : [];
                                    return (
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
                                            {msg.role === 'assistant' && citationItems.length > 0 && (
                                                <div className="nb-chat-citation-list">
                                                    {citationItems.slice(0, 8).map((citation, citationIndex) => (
                                                        <button
                                                            key={`${citation.citationLabel || citationIndex}-${citation.articleId || citation.url || citationIndex}`}
                                                            type="button"
                                                            className="nb-chat-citation-row"
                                                            onClick={() => handleOpenCitation(citation, msg.route || 'none')}
                                                        >
                                                            <span className="nb-chat-citation-row-title">
                                                                {citation.citationLabel ? `${citation.citationLabel} ` : ''}
                                                                {citation.title || '来源'}
                                                            </span>
                                                            <span className="nb-chat-citation-row-meta">{buildCitationMeta(citation)}</span>
                                                            {citation.core ? (
                                                                <span className="nb-chat-citation-row-core">{citation.core}</span>
                                                            ) : null}
                                                            {citation.reason ? (
                                                                <span className="nb-chat-citation-row-reason">{citation.reason}</span>
                                                            ) : null}
                                                        </button>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    );
                                })}
                            </div>
                            <div className="nb-chat-input-area">
                                <div className="nb-chat-input-wrapper">
                                    <textarea className="nb-chat-input nb-chat-textarea" disabled={isChatTemporarilyBlocked} placeholder={isChatTemporarilyBlocked ? '正文解析中，请稍后...' : (chatScope === 'article' ? '针对当前文章提问...' : '针对整个 notebook 提问...')} value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendChat(); } }} rows={3} />
                                    <button className="nb-chat-send-btn" onClick={handleSendChat} disabled={!chatInput.trim() || isChatStreaming || isChatTemporarilyBlocked}>{I.send}</button>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <>
                            <div className={`nb-panel ${isSourceDetailMode ? 'nb-right-full' : 'nb-right-top'}`}>
                                <SourcePanel
                                    notebookId={notebook.id}
                                    onAddSource={() => setShowAddSource(true)}
                                    onCollapsePanel={() => applyLayoutMode('focus')}
                                    onSourcesImported={handleSourcesImported}
                                    onDetailViewChange={setIsSourceDetailMode}
                                    pendingSearchRequest={pendingSourceSearch}
                                    onSearchHandled={(requestId) => {
                                        setPendingSourceSearch((current) => (current?.requestId === requestId ? null : current));
                                    }}
                                />
                            </div>

                            {/* Notes Panel */}
                            {!isSourceDetailMode ? (
                            <div className="nb-panel nb-right-bottom">
                                <div className="nb-panel-header">
                                    <span className="nb-panel-icon">{I.note}</span>
                                    <span className="nb-panel-title">笔记</span>
                                    <button type="button" className="nb-panel-action-btn" onClick={() => void handleExportNotebook()}>
                                        导出本本
                                    </button>
                                    <span className="nb-panel-badge">{notes.length}</span>
                                </div>
                                <div className="nb-panel-body nb-notes-body">
                                    <div className="nb-notes-filter">
                                        <input className="input" placeholder="按标签筛选笔记" value={noteFilterTag} onChange={(event) => setNoteFilterTag(event.target.value)} />
                                    </div>
                                    {notesFeedback ? (
                                        <p className="nb-notes-feedback">{notesFeedback}</p>
                                    ) : null}
                                    <div className="nb-notes-list">
                                        {notes.filter((note) => {
                                            const keyword = noteFilterTag.trim().toLowerCase();
                                            if (!keyword) return true;
                                            return (note.tags || []).some((tag) => String(tag).toLowerCase().includes(keyword));
                                        }).map(note => (
                                            <div key={note.id} className="nb-note-card">
                                                <div className="nb-note-card-inner" onClick={() => openExistingNote(note)}>
                                                    <div className="nb-note-card-icon">{I.edit}</div>
                                                    <div className="nb-note-card-info">
                                                        <span className="nb-note-card-title">{note.title}</span>
                                                        <span className="nb-note-card-sub">{note.type} · {note.sources} 个来源 · {note.time}</span>
                                                    </div>
                                                    <button
                                                        type="button"
                                                        className="nb-note-card-more"
                                                        onClick={(event) => {
                                                            event.stopPropagation();
                                                            setNoteActionMenuId((current) => (current === note.id ? null : note.id));
                                                        }}
                                                        title="更多操作"
                                                    >
                                                        {I.more}
                                                    </button>
                                                    {noteActionMenuId === note.id ? (
                                                        <div ref={noteActionMenuRef} className="nb-note-card-menu">
                                                            <button type="button" onClick={(event) => { event.stopPropagation(); setNoteActionMenuId(null); openExistingNote(note); }}>编辑</button>
                                                            <button type="button" onClick={(event) => { event.stopPropagation(); setNoteActionMenuId(null); void exportNote(note.id); }}>导出</button>
                                                            <button type="button" className="danger" onClick={(event) => { event.stopPropagation(); setNoteActionMenuId(null); void handleDeleteNote(note.id); }}>删除</button>
                                                        </div>
                                                    ) : null}
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
                            ) : null}
                        </>
                    )}
                </div>
                ) : null}

                {layoutHasRightRail ? (
                    <div className="nb-collapsed-rail nb-collapsed-rail-right">
                        <button type="button" className="nb-collapsed-rail-btn" onClick={() => applyLayoutMode('triple')} title="展开右栏">
                            {I.collapseRight}
                        </button>
                    </div>
                ) : null}
            </div>

            {highlightToolbar.visible ? (
                <div
                    ref={selectionToolbarRef}
                    className="nb-selection-toolbar"
                    style={{ left: `${highlightToolbar.x}px`, top: `${highlightToolbar.y}px` }}
                >
                    <div className="nb-selection-toolbar-colors">
                        {['yellow', 'blue', 'green', 'pink'].map((color) => (
                            <button
                                key={color}
                                type="button"
                                className={`nb-highlight-color-btn ${color}`}
                                title={`高亮：${color}`}
                                disabled={isPersistingHighlight}
                                onClick={() => { void createHighlightFromToolbar({ color }); }}
                            />
                        ))}
                    </div>
                    <div className="nb-selection-toolbar-actions">
                        <button
                            type="button"
                            className="nb-selection-toolbar-btn"
                            disabled={isPersistingHighlight}
                            onClick={openCommentComposer}
                            title="添加批注"
                        >
                            {I.comment}
                        </button>
                        <button
                            type="button"
                            className="nb-selection-toolbar-btn"
                            onClick={async () => {
                                const text = (highlightToolbar.text || '').trim();
                                if (!text) return;
                                await navigator.clipboard.writeText(text);
                                setHighlightToolbar((prev) => ({ ...prev, visible: false }));
                                clearTextSelection();
                                pushChatFeedback('已复制选中文本');
                            }}
                            title="复制"
                        >
                            {I.copy}
                        </button>
                        <button
                            type="button"
                            className="nb-selection-toolbar-btn"
                            onClick={() => {
                                const text = (highlightToolbar.text || '').trim();
                                if (!text) return;
                                applyLayoutMode('triple');
                                setShowAiChat(true);
                                setChatScope('article');
                                setChatInput(`请结合这段原文回答：\n${text}`);
                                setHighlightToolbar((prev) => ({ ...prev, visible: false }));
                                clearTextSelection();
                            }}
                            title="发送给助手"
                        >
                            {I.chat}
                        </button>
                        <button
                            type="button"
                            className="nb-selection-toolbar-btn"
                            disabled={isPersistingHighlight}
                            onClick={() => { void createHighlightFromToolbar({ color: 'yellow', openNote: true }); }}
                            title="生成笔记"
                        >
                            {I.addNote}
                        </button>
                        <button
                            type="button"
                            className="nb-selection-toolbar-btn danger"
                            disabled={isPersistingHighlight}
                            onClick={() => { void handleDeleteHighlightFromSelection(); }}
                            title="删除高亮"
                        >
                            {I.deleteChat}
                        </button>
                    </div>
                </div>
            ) : null}

            {commentComposer.open ? (
                <div
                    className="nb-comment-composer-overlay"
                    onMouseDown={(event) => {
                        if (event.target === event.currentTarget) {
                            closeCommentComposer();
                        }
                    }}
                >
                    <div className="nb-comment-composer-modal" role="dialog" aria-modal="true" aria-label="添加批注">
                        <div className="nb-comment-composer-header">
                            <h4>添加批注</h4>
                            <button type="button" className="nb-icon-btn-sm" onClick={closeCommentComposer} title="关闭">
                                {I.close}
                            </button>
                        </div>
                        <p className="nb-comment-composer-hint">可选。留空将仅创建高亮。</p>
                        <textarea
                            className="nb-comment-composer-input"
                            placeholder="输入批注内容..."
                            value={commentComposer.value}
                            onChange={(event) => {
                                setCommentComposer((prev) => ({ ...prev, value: event.target.value.slice(0, 280) }));
                            }}
                            autoFocus
                            rows={5}
                            maxLength={280}
                        />
                        <div className="nb-comment-composer-footer">
                            <span className="nb-comment-composer-count">{commentComposer.value.length}/280</span>
                            <div className="nb-comment-composer-actions">
                                <button
                                    type="button"
                                    className="nb-panel-action-btn"
                                    onClick={closeCommentComposer}
                                    disabled={isPersistingHighlight}
                                >
                                    取消
                                </button>
                                <button
                                    type="button"
                                    className="nb-comment-composer-submit"
                                    onClick={() => { void submitCommentComposer(); }}
                                    disabled={isPersistingHighlight}
                                >
                                    {isPersistingHighlight ? '保存中...' : '保存批注'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            ) : null}

            {showSettings && <SettingsModal initialTab={settingsInitialTab} onClose={() => setShowSettings(false)} />}
            {showAddSource && (
                <AddSourceModal
                    notebookId={notebook.id}
                    onClose={() => setShowAddSource(false)}
                    onImported={handleSourcesImported}
                    onStartSearch={handleStartSourceSearch}
                />
            )}
            {noteModalData && (
                <NoteModal
                    note={noteModalData}
                    onClose={() => setNoteModalData(null)}
                    onSave={handleSaveNote}
                    onDelete={handleDeleteNote}
                    onExport={exportNote}
                    onOpenSourceMarker={handleOpenNoteSourceMarker}
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
