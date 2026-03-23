/**
 * remark-processor — stdin JSON → unified 处理 → stdout JSON
 *
 * 输入: { "markdown": "..." }
 * 输出: { "mdast": {...}, "cleanMarkdown": "...", "html": "...",
 *         "toc": [...], "readingTime": {...}, "fixes": {...} }
 */

import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import remarkStringify from "remark-stringify";
import remarkRehype from "remark-rehype";
import rehypeSlug from "rehype-slug";
import rehypeStringify from "rehype-stringify";

import fixBrokenParagraphs from "./plugins/fix-broken-paragraphs.mjs";
import fixHeadingLevels from "./plugins/fix-heading-levels.mjs";
import fixListIndent from "./plugins/fix-list-indent.mjs";
import fixCodeBlocks from "./plugins/fix-code-blocks.mjs";
import fixTables from "./plugins/fix-tables.mjs";
import fixLinks from "./plugins/fix-links.mjs";
import compressBlankLines from "./plugins/compress-blank-lines.mjs";
import fixOcrSpacing from "./plugins/fix-ocr-spacing.mjs";
import extractToc from "./plugins/extract-toc.mjs";
import readingTime from "./plugins/reading-time.mjs";

async function processMarkdown(markdown) {
  const fixes = { appliedCount: 0 };

  // ========== phase 1 解析 + 修复 ==========
  // 先构建修复管线，每个插件返回修复计数
  const fixProcessor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(wrapCounter(fixBrokenParagraphs, fixes))
    .use(wrapCounter(fixHeadingLevels, fixes))
    .use(wrapCounter(fixListIndent, fixes))
    .use(wrapCounter(fixCodeBlocks, fixes))
    .use(wrapCounter(fixTables, fixes))
    .use(wrapCounter(fixLinks, fixes))
    .use(wrapCounter(compressBlankLines, fixes))
    .use(wrapCounter(fixOcrSpacing, fixes))
    .use(extractToc)
    .use(readingTime)
    .use(remarkStringify, { bullet: "-", emphasis: "*", strong: "*" });

  const fixResult = await fixProcessor.process(markdown);
  const mdast = fixProcessor.parse(markdown);

  // 对修复后的 markdown 再做一次解析拿到干净的 AST
  const cleanMarkdown = String(fixResult);
  const cleanAst = fixProcessor.parse(cleanMarkdown);

  // ========== phase 2 渲染 HTML ==========
  const htmlProcessor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeSlug)
    .use(rehypeStringify, { allowDangerousHtml: true });

  const htmlResult = await htmlProcessor.process(cleanMarkdown);

  return {
    mdast: cleanAst,
    cleanMarkdown,
    html: String(htmlResult),
    toc: fixResult.data.toc || [],
    readingTime: fixResult.data.readingTime || { minutes: 1, words: 0, characters: 0 },
    fixes,
  };
}

/**
 * 包装插件，累计修复计数到 fixes 对象。
 */
function wrapCounter(pluginFactory, fixes) {
  return function wrappedPlugin() {
    const inner = pluginFactory();
    return (tree, file) => {
      const count = inner(tree, file);
      if (typeof count === "number") {
        fixes.appliedCount += count;
      }
    };
  };
}

// ── stdin/stdout 通信 ────────────────────────────────────────────

async function main() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const input = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
  const result = await processMarkdown(input.markdown || "");
  process.stdout.write(JSON.stringify(result));
}

main().catch((err) => {
  process.stderr.write(JSON.stringify({ error: err.message }));
  process.exit(1);
});
