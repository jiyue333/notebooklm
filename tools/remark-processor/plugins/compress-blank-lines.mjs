/**
 * 连续空行压缩：移除 AST 中连续的空段落节点。
 */
import { visit } from "unist-util-visit";

export default function compressBlankLines() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "root", (node) => {
      const filtered = [];
      let prevEmpty = false;
      for (const child of node.children) {
        const isEmpty =
          child.type === "paragraph" &&
          child.children?.length === 1 &&
          child.children[0].type === "text" &&
          child.children[0].value.trim() === "";
        if (isEmpty && prevEmpty) {
          fixed++;
          continue;
        }
        prevEmpty = isEmpty;
        filtered.push(child);
      }
      node.children = filtered;
    });
    return fixed;
  };
}
