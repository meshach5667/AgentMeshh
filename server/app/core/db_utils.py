from typing import Any, cast

from sqlalchemy.engine import CursorResult


def rowcount(result: Any) -> int:
    """Rows affected by an UPDATE/DELETE executed through AsyncSession.execute."""
    return int(cast(CursorResult, result).rowcount)
