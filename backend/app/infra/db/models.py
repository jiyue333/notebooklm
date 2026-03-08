from __future__ import annotations


def import_models() -> None:
    """Import SQLAlchemy model modules so Alembic can discover them.

    The imports stay local so importing this helper does not have side effects
    before metadata discovery is actually needed.
    """
    from app.modules.auth import models as _auth_models  # noqa: F401
    from app.modules.notebooks import models as _notebook_models  # noqa: F401
    from app.modules.notes import models as _note_models  # noqa: F401
