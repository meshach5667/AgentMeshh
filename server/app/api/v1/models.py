from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_roles
from app.core.ratelimit import limiters
from app.models.user import User, UserRole
from app.schemas.model import (
    ArtifactCreate,
    ArtifactOut,
    ArtifactUpdate,
    CommunityModelImport,
    CommunityModelPreview,
    GgufFileOut,
    ModelCreate,
    ModelOut,
)
from app.services import community_model_service, huggingface, model_service

router = APIRouter()
customer_only = require_roles(UserRole.customer)


async def _limit_hf_lookups(user: User) -> None:
    """Each import or preview calls Hugging Face; keep one customer from hammering it through AgentMesh."""
    allowed, retry_after = await limiters.requests.allow(
        f"community-model:{user.id}", settings.COMMUNITY_MODEL_IMPORTS_PER_MINUTE
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many Hugging Face lookups; wait a minute",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


@router.get("", response_model=list[ModelOut])
async def list_models(db: AsyncSession = Depends(get_db)):
    return await model_service.list_models(db)


@router.get("/community", response_model=list[ModelOut])
async def list_community_models(db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    """Models the caller imported from Hugging Face. Nobody else can see or deploy them."""
    return await community_model_service.list_models(db, user)


@router.get("/community/preview", response_model=CommunityModelPreview)
async def preview_community_model(
    repo: str = Query(max_length=500),
    revision: str | None = Query(None, max_length=100),
    user=Depends(customer_only),
):
    """Look up a public Hugging Face repository: its license and the GGUF files that could be imported."""
    await _limit_hf_lookups(user)
    info = await community_model_service.preview(repo, revision)
    return CommunityModelPreview(
        repo=info.repo,
        revision=info.commit,
        license=info.license_name or info.license,
        license_problem=huggingface.license_problem(info.license),
        architecture=info.architecture,
        context_length=info.context_length,
        files=[
            GgufFileOut(
                name=f.name,
                size_bytes=f.size,
                quantization=f.quantization,
                problem=huggingface.file_problem(f),
                **community_model_service.estimated_requirements(f.size),
            )
            for f in info.files
        ],
    )


@router.post("/community", response_model=ModelOut, status_code=201)
async def import_community_model(
    req: CommunityModelImport, db: AsyncSession = Depends(get_db), user=Depends(customer_only)
):
    """Import one GGUF file from a public Hugging Face repository, pinned to the current commit and its
    SHA-256. The model is private to the caller and runs only on nodes whose provider opted in."""
    await _limit_hf_lookups(user)
    return await community_model_service.import_model(db, user, req)


@router.get("/community/{id}", response_model=ModelOut)
async def get_community_model(id: str, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    return await community_model_service.get_model(db, user, id)


@router.delete("/community/{id}", status_code=204)
async def withdraw_community_model(id: str, db: AsyncSession = Depends(get_db), user=Depends(customer_only)):
    await community_model_service.withdraw(db, user, id)
    return Response(status_code=204)


@router.get("/{id}", response_model=ModelOut)
async def get_model(id: str, db: AsyncSession = Depends(get_db)):
    return await model_service.get_model(db, id)


@router.post("", response_model=ModelOut)
async def create_model(
    model: ModelCreate,
    db: AsyncSession = Depends(get_db),
    staff=Depends(require_roles(UserRole.operator, UserRole.admin)),
):
    # Catalog entries are created unapproved; approval is a separate, explicit operator decision.
    return await model_service.create_model(db, model, actor_id=staff.id)


@router.post("/{id}/approval", response_model=ModelOut)
async def set_model_approval(
    id: str,
    approved: bool = True,
    db: AsyncSession = Depends(get_db),
    staff=Depends(require_roles(UserRole.operator, UserRole.admin)),
):
    """Approve (or withdraw) a catalog entry for deployment. Approval does not guarantee a node can run it."""
    return await model_service.approve_model(db, id, approved, actor_id=staff.id)


@router.post("/{id}/artifacts", response_model=ArtifactOut, status_code=201)
async def add_artifact(
    id: str,
    artifact: ArtifactCreate,
    db: AsyncSession = Depends(get_db),
    staff=Depends(require_roles(UserRole.operator, UserRole.admin)),
):
    """Declare that a runtime can serve this model, from a pinned source. Validated like deployments are."""
    return await model_service.add_artifact(db, id, artifact, actor_id=staff.id)


@router.patch("/{id}/artifacts/{artifact_id}", response_model=ArtifactOut)
async def update_artifact(
    id: str,
    artifact_id: str,
    update: ArtifactUpdate,
    db: AsyncSession = Depends(get_db),
    staff=Depends(require_roles(UserRole.operator, UserRole.admin)),
):
    return await model_service.set_artifact_enabled(db, id, artifact_id, update.is_enabled, actor_id=staff.id)
