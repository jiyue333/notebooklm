/**
 * 代码块闭合修复：检查 code 节点是否有未闭合的围栏标记残留在 value 中。
 */
import { visit } from "unist-util-visit";

export default function fixCodeBlocks() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "code", (node) => {
      if (!node.value) return;
      // 移除意外残留的围栏标记
      const lines = node.value.split("\n");
      const cleaned = lines.filter(
        (line) => !/^(`{3,}|~{3,})\s*$/.test(line.trim())
      );
      if (cleaned.length !== lines.length) {
        node.value = cleaned.join("\n");
        fixed++;
      }
    });
    return fixed;
  };
}
