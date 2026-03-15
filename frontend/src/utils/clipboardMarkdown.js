const BLOCK_BREAK = '\n\n';

function normalizeText(value) {
    return value.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

function escapeMarkdownText(value) {
    return value.replace(/([\\`*_{}[\]()#+\-.!|>])/g, '\\$1');
}

function cleanInlineText(value) {
    return value.replace(/\s+/g, ' ').trim();
}

function normalizeMarkdown(value) {
    return normalizeText(value)
        .replace(/[ \t]+\n/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function absoluteUrl(value) {
    if (!value) return '';
    return value.trim();
}

function serializeTextNode(node, context) {
    if (context.inPre) {
        return node.textContent || '';
    }
    return (node.textContent || '').replace(/\s+/g, ' ');
}

function serializeInlineChildren(node, context) {
    return Array.from(node.childNodes)
        .map((child) => serializeNode(child, context))
        .join('')
        .replace(/\s+\n/g, '\n')
        .replace(/\n\s+/g, '\n');
}

function serializeList(node, context) {
    const ordered = node.tagName === 'OL';
    const items = Array.from(node.children)
        .filter((child) => child.tagName === 'LI')
        .map((child, index) => {
            const prefix = ordered ? `${index + 1}. ` : '- ';
            const content = normalizeMarkdown(serializeInlineChildren(child, { ...context, listDepth: context.listDepth + 1 }));
            const indented = content
                .split('\n')
                .map((line, lineIndex) => `${lineIndex === 0 ? prefix : ' '.repeat(prefix.length)}${line}`)
                .join('\n');
            return indented;
        })
        .filter(Boolean);
    return items.join('\n');
}

function serializeBlockquote(node, context) {
    const content = normalizeMarkdown(serializeInlineChildren(node, context));
    if (!content) return '';
    return content
        .split('\n')
        .map((line) => `> ${line}`)
        .join('\n');
}

function serializeTable(node) {
    return node.outerHTML || '';
}

function serializeNode(node, context = { inPre: false, listDepth: 0 }) {
    if (node.nodeType === Node.TEXT_NODE) {
        return serializeTextNode(node, context);
    }
    if (node.nodeType !== Node.ELEMENT_NODE) {
        return '';
    }

    const tag = node.tagName.toUpperCase();
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(tag)) {
        return '';
    }
    if (tag === 'BR') {
        return '\n';
    }
    if (tag === 'HR') {
        return '\n\n---\n\n';
    }
    if (tag === 'IMG') {
        const src = absoluteUrl(node.getAttribute('src'));
        if (!src) return '';
        const alt = cleanInlineText(node.getAttribute('alt') || '') || 'image';
        return `![${escapeMarkdownText(alt)}](${src})`;
    }
    if (tag === 'A') {
        const href = absoluteUrl(node.getAttribute('href'));
        const label = cleanInlineText(serializeInlineChildren(node, context)) || href;
        if (!href) return label;
        return `[${label}](${href})`;
    }
    if (tag === 'STRONG' || tag === 'B') {
        const content = cleanInlineText(serializeInlineChildren(node, context));
        return content ? `**${content}**` : '';
    }
    if (tag === 'EM' || tag === 'I') {
        const content = cleanInlineText(serializeInlineChildren(node, context));
        return content ? `*${content}*` : '';
    }
    if (tag === 'CODE') {
        const content = node.textContent || '';
        if (context.inPre) return content;
        return content ? `\`${content.replace(/`/g, '\\`')}\`` : '';
    }
    if (tag === 'PRE') {
        const content = normalizeText(node.textContent || '').trim();
        return content ? `\n\n\`\`\`\n${content}\n\`\`\`\n\n` : '';
    }
    if (tag === 'UL' || tag === 'OL') {
        const content = serializeList(node, context);
        return content ? `${BLOCK_BREAK}${content}${BLOCK_BREAK}` : '';
    }
    if (tag === 'BLOCKQUOTE') {
        const content = serializeBlockquote(node, context);
        return content ? `${BLOCK_BREAK}${content}${BLOCK_BREAK}` : '';
    }
    if (tag === 'TABLE') {
        const content = serializeTable(node);
        return content ? `${BLOCK_BREAK}${content}${BLOCK_BREAK}` : '';
    }
    if (/^H[1-6]$/.test(tag)) {
        const level = Number(tag.slice(1));
        const content = cleanInlineText(serializeInlineChildren(node, context));
        return content ? `${BLOCK_BREAK}${'#'.repeat(level)} ${content}${BLOCK_BREAK}` : '';
    }
    if (['P', 'DIV', 'SECTION', 'ARTICLE', 'FIGURE', 'FIGCAPTION'].includes(tag)) {
        const content = normalizeMarkdown(serializeInlineChildren(node, context));
        return content ? `${BLOCK_BREAK}${content}${BLOCK_BREAK}` : '';
    }
    return serializeInlineChildren(node, context);
}

export function htmlToMarkdown(html) {
    if (!html?.trim()) return '';
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const markdown = Array.from(doc.body.childNodes).map((node) => serializeNode(node)).join('');
    return normalizeMarkdown(markdown);
}

export function extractClipboardMarkdown(clipboardData) {
    const html = clipboardData?.getData?.('text/html') || '';
    if (html.trim()) {
        const markdown = htmlToMarkdown(html);
        if (markdown) {
            return markdown;
        }
    }
    return normalizeText(clipboardData?.getData?.('text/plain') || '');
}
