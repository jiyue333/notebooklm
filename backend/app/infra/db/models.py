from __future__ import annotations


def import_models() -> None:
    """
    Import SQLAlchemy model modules so Alembic can discover them.

    """
    from app.modules.agent.chat import models as _ai_chat_models  # noqa: F401
    from app.modules.agent.summary import models as _ai_summary_models  # noqa: F401
    from app.modules.auth import models as _auth_models  # noqa: F401
    from app.modules.jobs import models as _job_models  # noqa: F401
    from app.modules.notebooks import models as _notebook_models  # noqa: F401
    from app.modules.notes import models as _note_models  # noqa: F401
    from app.modules.search.sessions import models as _search_models  # noqa: F401
