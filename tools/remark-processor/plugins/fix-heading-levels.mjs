/**
 * 标题级别修正：确保从 h1 开始，不跳级。
 * 例如文档只有 h3 和 h5 → 归一化为 h1 和 h2。
 */
import { visit } from "unist-util-visit";

export default function fixHeadingLevels() {
  return (tree) => {
    let fixed = 0;
    const depths = [];
    visit(tree, "heading", (node) => {
      depths.push(node.depth);
    });

    if (depths.length === 0) return fixed;

    const sorted = [...new Set(depths)].sort((a, b) => a - b);
    // 构建映射: 原始深度 → 归一化深度 (从 1 开始连续)
    const mapping = {};
    sorted.forEach((d, i) => {
      mapping[d] = i + 1;
    });

    // 如果已经正确就不改
    if (sorted[0] === 1 && sorted.every((d, i) => d === i + 1)) {
      return fixed;
    }

    visit(tree, "heading", (node) => {
      const newDepth = mapping[node.depth];
      if (newDepth !== undefined && newDepth !== node.depth) {
        node.depth = Math.min(newDepth, 6);
        fixed++;
      }
    });
    return fixed;
  };
}
