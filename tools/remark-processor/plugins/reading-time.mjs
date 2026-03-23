/**
 * 阅读时间估算：中文按字数 (400字/分钟)，英文按词数 (250词/分钟)。
 * 结果写入 file.data.readingTime。
 */
import { visit } from "unist-util-visit";

const CJK = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/g;
const WORDS = /[\w'-]+/g;

export default function readingTime() {
  return (tree, file) => {
    let cjkChars = 0;
    let words = 0;

    visit(tree, "text", (node) => {
      if (!node.value) return;
      const cjkMatches = node.value.match(CJK);
      if (cjkMatches) cjkChars += cjkMatches.length;
      const stripped = node.value.replace(CJK, " ");
      const wordMatches = stripped.match(WORDS);
      if (wordMatches) words += wordMatches.length;
    });

    const cjkMinutes = cjkChars / 400;
    const enMinutes = words / 250;
    const totalMinutes = Math.max(1, Math.ceil(cjkMinutes + enMinutes));

    file.data.readingTime = {
      minutes: totalMinutes,
      words,
      characters: cjkChars + words,
    };
  };
}
