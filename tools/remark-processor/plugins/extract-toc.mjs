/**
 * 提取标题生成 TOC 数组，写入 file.data.toc。
 */
import { visit } from "unist-util-visit";

export default function extractToc() {
  return (tree, file) => {
    const toc = [];
    let counter = 0;
    visit(tree, "heading", (node) => {
      counter++;
      const text = node.children
        ?.filter((c) => c.type === "text" || c.type === "inlineCode")
        .map((c) => c.value || "")
        .join("")
        .trim();
      if (!text) return;

      const id = `sec-${counter}`;
      const anchor = text
        .toLowerCase()
        .replace(/[^\w\u4e00-\u9fff]+/g, "-")
        .replace(/^-|-$/g, "");

      toc.push({
        id,
        title: text,
        level: node.depth,
        anchor: anchor || `heading-${counter}`,
      });
    });
    file.data.toc = toc;
  };
}
