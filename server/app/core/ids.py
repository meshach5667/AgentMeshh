import uuid

from fastapi import HTTPException


def parse_uuid(value: str | uuid.UUID, resource: str = "Resource") -> uuid.UUID:
    """Parse a client-supplied identifier. Malformed IDs are reported as not found rather than a server error."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=404, detail=f"{resource} not found") from None
