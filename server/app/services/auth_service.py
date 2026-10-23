from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import Customer, Provider, User, UserRole
from app.schemas.auth import UserCreate, UserLogin
from app.services import audit_service


async def register_user(db: AsyncSession, user_data: UserCreate):
    result = await db.execute(select(User).filter(User.email == user_data.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=user_data.email, hashed_password=get_password_hash(user_data.password), role=user_data.role.value)
    db.add(user)
    await db.flush()  # assign user.id without committing, so user + profile are created atomically

    if user.role == UserRole.provider.value:
        db.add(Provider(user_id=user.id))
    elif user.role == UserRole.customer.value:
        db.add(Customer(user_id=user.id))
    audit_service.record(
        db,
        actor_id=user.id,
        action="user.registered",
        resource_type="user",
        resource_id=user.id,
        details={"role": user.role},
    )
    await db.commit()
    await db.refresh(user)
    access_token = create_access_token(subject=user.id)
    return {"access_token": access_token, "token_type": "bearer", "user": user}


async def login(db: AsyncSession, user_data: UserLogin):
    result = await db.execute(select(User).filter(User.email == user_data.email))
    user = result.scalars().first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        audit_service.record(
            db,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            resource_type="user",
            resource_id=user.id if user else None,
            details={"email": user_data.email},
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    audit_service.record(db, actor_id=user.id, action="auth.login", resource_type="user", resource_id=user.id)
    await db.commit()

    access_token = create_access_token(subject=user.id)
    return {"access_token": access_token, "token_type": "bearer", "user": user}
