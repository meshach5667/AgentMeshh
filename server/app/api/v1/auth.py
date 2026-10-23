from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.ratelimit import limiters
from app.schemas.auth import AuthResponse, UserCreate, UserLogin, UserOut
from app.services import auth_service

router = APIRouter()


async def _throttle(request: Request, email: str) -> None:
    """Limit password attempts per client address and per account (slows credential stuffing and guessing)."""
    client = request.client.host if request.client else "unknown"
    for key in (f"auth:ip:{client}", f"auth:email:{email.strip().lower()}"):
        allowed, retry_after = await limiters.requests.allow(key, settings.AUTH_RATE_LIMIT_PER_MINUTE)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again shortly.",
                headers={"Retry-After": str(max(1, int(retry_after)))},
            )


@router.post("/register", response_model=AuthResponse)
async def register(user: UserCreate, request: Request, db: AsyncSession = Depends(get_db)):
    await _throttle(request, user.email)
    return await auth_service.register_user(db, user)


@router.post("/login", response_model=AuthResponse)
async def login(user: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    await _throttle(request, user.email)
    return await auth_service.login(db, user)


@router.get("/me", response_model=UserOut)
async def get_me(current_user=Depends(get_current_user)):
    return current_user
