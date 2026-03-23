/**
 * 表格格式修复：确保 table 节点的行列数一致（用空单元格补齐短行）。
 */
import { visit } from "unist-util-visit";

export default function fixTables() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "table", (node) => {
      if (!node.children?.length) return;
      const maxCols = Math.max(...node.children.map((row) => row.children?.length || 0));
      for (const row of node.children) {
        if (!row.children) row.children = [];
        while (row.children.length < maxCols) {
          row.children.push({
            type: "tableCell",
            children: [{ type: "text", value: "" }],
          });
          fixed++;
        }
      }
    });
    return fixed;
  };
}
