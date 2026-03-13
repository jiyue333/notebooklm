"""AI 用户行为事件 Tracker。

记录前端上报的用户交互事件（如 follow_up / citation_open / answer_copy 等），
聚合 observability context 绑定 + metrics 上报 + 结构化日志三个步骤。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_ai_user_action

if TYPE_CHECKING:
    from app.modules.auth.models import User

logger = structlog.get_logger(__name__)


async def record_ai_user_event(
    *,
    user: User,
    notebook_id: str,
    operation: str,
    action: str,
    route: str | None = None,
    article_id: str | None = None,
    conversation_id: str | None = None,
) -> None:
    normalized_route = route or "none"
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        article_id=article_id,
        conversation_id=conversation_id,
        ai_operation=operation,
        ai_action=action,
        ai_route=normalized_route,
    )
    observe_ai_user_action(
        operation=operation,
        action=action,
        route=normalized_route,
    )
    logger.info(
        "ai.user_action",
        notebook_id=notebook_id,
        article_id=article_id,
        conversation_id=conversation_id,
        operation=operation,
        action=action,
        route=normalized_route,
    )
