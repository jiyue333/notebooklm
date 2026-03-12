from __future__ import annotations

MAX_SEARCH_ERROR_MESSAGE_LENGTH = 4000


def sanitize_search_error_message(error: Exception) -> str:
    message = str(error).replace("\x00", "").strip()
    if len(message) <= MAX_SEARCH_ERROR_MESSAGE_LENGTH:
        return message
    return f"{message[:MAX_SEARCH_ERROR_MESSAGE_LENGTH - 1]}..."
