/**
 * OCR 乱码间距修复：
 * - 中文字符间的多余空格移除
 * - 英文单词间的多余空格压缩
 * - 常见 OCR 错误字符清理
 */
import { visit } from "unist-util-visit";

const CJK_RANGE = /[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]/;
const MULTI_SPACE = / {2,}/g;
const CJK_SPACE_CJK = /([\u4e00-\u9fff])\s+([\u4e00-\u9fff])/g;

export default function fixOcrSpacing() {
  return (tree) => {
    let fixed = 0;
    visit(tree, "text", (node) => {
      if (!node.value) return;
      let v = node.value;
      const original = v;

      // 中文字符间不需要空格
      v = v.replace(CJK_SPACE_CJK, "$1$2");
      // 多个连续空格 → 单个
      v = v.replace(MULTI_SPACE, " ");
      // 零宽字符清理
      v = v.replace(/[\u200b\u200c\u200d\ufeff]/g, "");

      if (v !== original) {
        node.value = v;
        fixed++;
      }
    });
    return fixed;
  };
}
