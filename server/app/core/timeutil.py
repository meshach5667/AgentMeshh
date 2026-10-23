from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching the naive UTC columns in the schema."""
    return datetime.now(UTC).replace(tzinfo=None)
