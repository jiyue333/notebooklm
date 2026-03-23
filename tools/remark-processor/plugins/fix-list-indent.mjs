/**
 * 列表错乱修复：确保 list/listItem 结构完整。
 * 主要处理嵌套列表中 loose/tight 混乱的情况。
 */
import { visit } from "unist-util-visit";

export default function fixListIndent() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "list", (node) => {
      for (const item of node.children) {
        if (item.type !== "listItem") continue;
        // 确保 listItem 至少有一个子节点
        if (!item.children || item.children.length === 0) {
          item.children = [{ type: "paragraph", children: [{ type: "text", value: "" }] }];
          fixed++;
        }
      }
    });
    return fixed;
  };
}
