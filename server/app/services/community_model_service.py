"""Community models: public Hugging Face GGUF files a customer imports for their own deployments.

They are private to the importing customer, served only by llama.cpp from a commit-pinned, SHA-256 verified
file, and scheduled only onto nodes whose provider opted in. Requirements are estimated from the file size.
Operators can disable an import's artifact (takedown) or approve the model into the reviewed catalog.
"""

import math
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ids import parse_uuid
from app.core.timeutil import utcnow
from app.models.deployment import Deployment
from app.models.model import Model, ModelArtifact
from app.models.user import Customer, User
from app.schemas.model import CommunityModelImport
from app.services import audit_service, huggingface
from app.services.deployment_lifecycle import TERMINAL


async def _customer(db: AsyncSession, user: User) -> Customer:
    customer = (await db.execute(select(Customer).where(Customer.user_id == user.id))).scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=403, detail="Customer account required")
    return customer


def _active(customer_id: uuid.UUID):
    return select(Model).where(Model.owner_customer_id == customer_id, Model.withdrawn_at.is_(None))


def estimated_requirements(size_bytes: int) -> dict:
    """llama.cpp memory-maps the whole file and adds KV cache and compute buffers on top."""
    size_mb = math.ceil(size_bytes / 2**20)
    return {
        "min_ram_mb": math.ceil(size_mb * 1.2) + 512,
        "min_disk_mb": math.ceil(size_mb * 1.05) + 256,
        "min_cpu_cores": 1 if size_mb < 1024 else 2,
    }


async def preview(ref_text: str, revision: str | None) -> huggingface.RepoInfo:
    return await huggingface.fetch_repo(huggingface.parse_reference(ref_text, revision=revision))


async def import_model(db: AsyncSession, user: User, req: CommunityModelImport) -> Model:
    if not settings.COMMUNITY_MODELS_ENABLED:
        raise HTTPException(status_code=403, detail="Importing community models is disabled on this AgentMesh")
    customer = await _customer(db, user)
    if not req.accept_terms:
        raise HTTPException(
            status_code=422, detail="Confirm that you may use this model under its license and AgentMesh's terms"
        )
    ref = huggingface.parse_reference(req.repo, file=req.file, revision=req.revision)
    if ref.file is None:
        raise HTTPException(status_code=422, detail="Choose which .gguf file to deploy")

    info = await huggingface.fetch_repo(ref)
    problem = huggingface.license_problem(info.license)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    gguf = info.file(ref.file)
    if gguf is None:
        raise HTTPException(status_code=422, detail=f"{ref.file} is not a GGUF file at this revision")
    problem = huggingface.file_problem(gguf)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    source_url = f"https://huggingface.co/{info.repo}/blob/{info.commit}/{gguf.name}"
    existing: Model | None = (
        (await db.execute(_active(customer.id).where(Model.source_url == source_url))).scalars().first()
    )
    if existing:
        return existing
    count = (
        await db.execute(
            select(func.count(Model.id)).where(Model.owner_customer_id == customer.id, Model.withdrawn_at.is_(None))
        )
    ).scalar() or 0
    if count >= settings.COMMUNITY_MODELS_PER_CUSTOMER:
        raise HTTPException(
            status_code=409,
            detail=f"You already have {count} imported models; remove one before importing another",
        )

    owner, repo_name = info.repo.split("/", 1)
    need = estimated_requirements(gguf.size)
    model = Model(
        name=(f"{repo_name} {gguf.quantization}" if gguf.quantization else repo_name)[:255],
        version=info.commit[:12],
        runtime="llamacpp",
        source="huggingface",
        source_url=source_url,
        publisher=owner[:255],
        family=info.architecture,
        quantization=gguf.quantization,
        format="gguf",
        license=info.license_name or info.license,
        context_length=info.context_length,
        download_size_mb=math.ceil(gguf.size / 2**20),
        gpu_required=False,
        requirements_estimated=True,
        is_approved=False,
        owner_customer_id=customer.id,
        **need,
    )
    db.add(model)
    await db.flush()
    db.add(
        ModelArtifact(
            model_id=model.id,
            runtime="llamacpp",
            source_type="huggingface",
            reference=info.repo,
            revision=info.commit,
            file=gguf.name,
            sha256=gguf.sha256,
            size_bytes=gguf.size,
            format="gguf",
            quantization=gguf.quantization,
            min_vram_mb=0,
            gpu_required=False,
            requirements_estimated=True,
            **need,
        )
    )
    audit_service.record(
        db,
        actor_id=user.id,
        action="model.community_imported",
        resource_type="model",
        resource_id=model.id,
        details={
            "repo": info.repo,
            "revision": info.commit,
            "file": gguf.name,
            "sha256": gguf.sha256,
            "license": info.license,
            "terms_accepted": True,
        },
    )
    await db.commit()
    await db.refresh(model)
    return model


async def list_models(db: AsyncSession, user: User) -> list[Model]:
    customer = await _customer(db, user)
    return list((await db.execute(_active(customer.id).order_by(Model.created_at.desc()))).scalars().all())


async def get_model(db: AsyncSession, user: User, model_id: str) -> Model:
    """The caller's own community model. Anyone else's is 404 so ids cannot be probed."""
    customer = await _customer(db, user)
    model: Model | None = (
        await db.execute(_active(customer.id).where(Model.id == parse_uuid(model_id, "Model")))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


async def withdraw(db: AsyncSession, user: User, model_id: str) -> None:
    model = await get_model(db, user, model_id)
    if model.is_approved:
        raise HTTPException(status_code=409, detail="An operator added this model to the catalog; it cannot be removed")
    running = (
        await db.execute(
            select(func.count(Deployment.id)).where(
                Deployment.model_id == model.id,
                Deployment.status.not_in([s.value for s in TERMINAL]),
            )
        )
    ).scalar() or 0
    if running:
        raise HTTPException(status_code=409, detail="Stop this model's deployments before removing it")
    model.withdrawn_at = utcnow()
    for artifact in model.artifacts:
        artifact.is_enabled = False
    audit_service.record(
        db, actor_id=user.id, action="model.community_withdrawn", resource_type="model", resource_id=model.id
    )
    await db.commit()
