/**
 * 合并断裂段落：连续的短文本节点（非标题/列表/代码）合并为一个段落。
 * 典型场景：OCR 或 PDF 解析将一段话拆成多个单行段落。
 */
import { visit } from "unist-util-visit";

export default function fixBrokenParagraphs() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "root", (node) => {
      const merged = [];
      let buffer = null;

      for (const child of node.children) {
        if (child.type === "paragraph" && isSingleTextNode(child)) {
          const text = extractText(child);
          // 短行且不以句末标点结束 → 可能是断裂段落
          if (buffer && text.length < 120 && !endsWithTerminal(extractText(buffer))) {
            appendText(buffer, " " + text);
            fixed++;
            continue;
          }
          if (text.length < 80 && !endsWithTerminal(text)) {
            buffer = child;
            merged.push(child);
            continue;
          }
        }
        buffer = null;
        merged.push(child);
      }
      node.children = merged;
    });
    return fixed;
  };
}

function isSingleTextNode(p) {
  return p.children?.length === 1 && p.children[0].type === "text";
}

function extractText(p) {
  return p.children?.[0]?.value || "";
}

function appendText(p, extra) {
  if (p.children?.[0]) p.children[0].value += extra;
}

function endsWithTerminal(s) {
  return /[.。!！?？;；:：\n]$/.test(s.trim());
}
