/**
 * 链接格式修复：清理空 href、修复常见的链接解析错误。
 */
import { visit } from "unist-util-visit";

export default function fixLinks() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "link", (node) => {
      // 移除空 URL 的链接 → 退化为纯文本
      if (!node.url || node.url.trim() === "") {
        node.type = "text";
        node.value = node.children?.map((c) => c.value || "").join("") || "";
        delete node.children;
        delete node.url;
        fixed++;
        return;
      }
      // 修复常见的双斜杠错误
      if (node.url.startsWith("http:///")) {
        node.url = node.url.replace("http:///", "http://");
        fixed++;
      }
      if (node.url.startsWith("https:///")) {
        node.url = node.url.replace("https:///", "https://");
        fixed++;
      }
    });
    return fixed;
  };
}
