"""Create (or promote) an operator or admin account. Operators cannot self-register through the API, so the
first one is created here, by someone with access to the server's database configuration.

    DATABASE_URL=... python scripts/create_operator.py ops@example.com            # prompts for a password
    AGENTMESH_OPERATOR_PASSWORD=... python scripts/create_operator.py ops@example.com --role admin

An existing account with that email is promoted (its password is left unchanged unless --reset-password).
The action is recorded in the audit log.
"""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import session_scope  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import audit_service  # noqa: E402

MIN_PASSWORD = 12


def read_password(confirm: bool = True) -> str:
    password = os.environ.get("AGENTMESH_OPERATOR_PASSWORD")
    if password is None:
        password = getpass.getpass("Password: ")
        if confirm and getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Passwords do not match")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"Operator passwords must be at least {MIN_PASSWORD} characters")
    return password


async def create_operator(email: str, role: str, reset_password: bool, password_reader=read_password) -> str:
    email = email.strip()
    async with session_scope() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalars().first()
        if user is None:
            user = User(email=email, hashed_password=get_password_hash(password_reader()), role=role, is_active=True)
            db.add(user)
            await db.flush()
            outcome = "created"
        else:
            previous = user.role
            user.role = role
            if reset_password:
                user.hashed_password = get_password_hash(password_reader())
            outcome = f"promoted from {previous}"
        audit_service.record(
            db,
            actor_id=None,
            action="user.operator_provisioned",
            resource_type="user",
            resource_id=user.id,
            details={"role": role, "outcome": outcome, "via": "scripts/create_operator.py"},
        )
        await db.commit()
        return outcome


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("--role", choices=[UserRole.operator.value, UserRole.admin.value], default=UserRole.operator.value)
    ap.add_argument("--reset-password", action="store_true", help="Also set a new password for an existing account")
    args = ap.parse_args()
    outcome = asyncio.run(create_operator(args.email, args.role, args.reset_password))
    print(f"{args.email}: {args.role} account {outcome}")


if __name__ == "__main__":
    main()
