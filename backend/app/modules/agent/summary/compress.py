"""内容压缩：减少代码块、长表格、图片等噪音。"""

from __future__ import annotations

import re


def compress_content(text: str, *, compress_code: bool = True) -> str:
    """对 clean_markdown 做降噪压缩。"""
    result = text

    if compress_code:
        result = _compress_code_blocks(result)

    result = _compress_tables(result)
    result = _compress_images(result)
    result = _collapse_blank_lines(result)

    return result.strip()


_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _compress_code_blocks(text: str) -> str:
    """保留代码块首行签名 + 行数占位。"""

    def _replacer(m: re.Match) -> str:
        lang = m.group(1) or ""
        body = m.group(2)
        lines = body.strip().splitlines()
        if len(lines) <= 3:
            return m.group(0)
        first_line = lines[0].strip()
        return f"```{lang}\n{first_line}\n... ({len(lines)} lines)\n```"

    return _CODE_BLOCK_RE.sub(_replacer, text)


_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)


def _compress_tables(text: str) -> str:
    """长表格只保留表头 + 前 2 行数据。"""
    lines = text.split("\n")
    result: list[str] = []
    table_rows: list[str] = []
    in_table = False

    for line in lines:
        is_table_row = bool(_TABLE_ROW_RE.match(line.strip()))

        if is_table_row:
            table_rows.append(line)
            in_table = True
        else:
            if in_table:
                result.extend(_truncate_table(table_rows))
                table_rows = []
                in_table = False
            result.append(line)

    if table_rows:
        result.extend(_truncate_table(table_rows))

    return "\n".join(result)


def _truncate_table(rows: list[str]) -> list[str]:
    # 表头行 + 分隔行 = 前 2 行, 数据行从第 3 行开始
    if len(rows) <= 5:
        return rows
    header = rows[:2]
    data = rows[2:]
    kept = data[:2]
    return header + kept + [f"| ... ({len(data) - 2} more rows) |"]


_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")


def _compress_images(text: str) -> str:
    return _IMAGE_RE.sub(lambda m: f"[图片: {m.group(1) or '无描述'}]", text)


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)
