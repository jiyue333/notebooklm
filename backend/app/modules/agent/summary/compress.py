"""内容压缩：减少代码块、长表格、图片等噪音。"""

from __future__ import annotations

import re


def compress_content(
    text: str,
    *,
    compress_code: bool = True,
    article_type: str = "general",
) -> str:
    """对 clean_markdown 做降噪压缩，并根据文档类型调整保留策略。"""
    result = text
    strategy = _resolve_strategy(article_type=article_type, compress_code=compress_code)

    if strategy["compress_code"]:
        result = _compress_code_blocks(result, keep_lines=int(strategy["code_keep_lines"]))

    result = _compress_tables(result, keep_rows=int(strategy["table_keep_rows"]))
    result = _compress_images(result)
    result = _collapse_blank_lines(result)
    return result.strip()


def _resolve_strategy(*, article_type: str, compress_code: bool) -> dict[str, int | bool]:
    normalized = (article_type or "general").strip().lower()
    base = {
        "compress_code": compress_code,
        "code_keep_lines": 1,
        "table_keep_rows": 2,
    }
    if normalized == "code_heavy":
        base["compress_code"] = False
        base["table_keep_rows"] = 2
    elif normalized == "research":
        base["compress_code"] = compress_code
        base["code_keep_lines"] = 2
        base["table_keep_rows"] = 4
    elif normalized in {"tutorial", "news"}:
        base["compress_code"] = compress_code
        base["code_keep_lines"] = 2
        base["table_keep_rows"] = 3
    return base


_CODE_BLOCK_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def _compress_code_blocks(text: str, *, keep_lines: int = 1) -> str:
    """保留代码块开头若干行 + 行数占位。"""
    keep = max(1, keep_lines)

    def _replacer(m: re.Match) -> str:
        lang = m.group(1) or ""
        body = m.group(2)
        lines = body.strip().splitlines()
        if len(lines) <= keep + 2:
            return m.group(0)
        preview = "\n".join(line.rstrip() for line in lines[:keep]).strip()
        if not preview:
            preview = lines[0].strip()
        omitted = max(0, len(lines) - keep)
        return f"```{lang}\n{preview}\n... ({omitted} more lines)\n```"

    return _CODE_BLOCK_RE.sub(_replacer, text)


_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)


def _compress_tables(text: str, *, keep_rows: int = 2) -> str:
    """长表格保留表头 + 前 N 行数据。"""
    rows_to_keep = max(1, keep_rows)
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
                result.extend(_truncate_table(table_rows, keep_rows=rows_to_keep))
                table_rows = []
                in_table = False
            result.append(line)

    if table_rows:
        result.extend(_truncate_table(table_rows, keep_rows=rows_to_keep))

    return "\n".join(result)


def _truncate_table(rows: list[str], *, keep_rows: int) -> list[str]:
    # 表头行 + 分隔行 = 前 2 行, 数据行从第 3 行开始
    if len(rows) <= keep_rows + 2:
        return rows
    header = rows[:2]
    data = rows[2:]
    kept = data[:keep_rows]
    omitted = max(0, len(data) - keep_rows)
    return header + kept + [f"| ... ({omitted} more rows) |"]


_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")


def _compress_images(text: str) -> str:
    return _IMAGE_RE.sub(lambda m: f"[图片: {m.group(1) or '无描述'}]", text)


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)
