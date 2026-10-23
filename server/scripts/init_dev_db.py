"""Create the schema and seed the Ollama catalog in a local SQLite dev database.

Postgres environments must use `alembic upgrade head` instead. SQLite cannot run every migration (it cannot
alter constraints), so this script builds the schema from the ORM models and reuses the catalog seed data
from migration 005.

    DATABASE_URL=sqlite+aiosqlite:///./dev.db python scripts/init_dev_db.py
"""

import asyncio
import importlib.util
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.core.timeutil import utcnow  # noqa: E402
from app.models import Base, Model, ModelArtifact  # noqa: E402


def _migration(name: str):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _catalog():
    return _migration("005_worker_protocol_and_lifecycle.py").CATALOG


async def main() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        raise SystemExit("Refusing to run against a non-SQLite database. Use `alembic upgrade head`.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        for tag, name, publisher, family, params, quant, lic, ctx, dl, ram, disk, cpu in _catalog():
            model_id = uuid.uuid5(uuid.NAMESPACE_URL, f"agentmesh:ollama:{tag}")
            if (await db.execute(select(Model).where(Model.id == model_id))).scalar_one_or_none():
                continue
            db.add(
                Model(
                    id=model_id,
                    name=name,
                    version=tag.split(":", 1)[1],
                    runtime="ollama",
                    source="ollama-registry",
                    is_approved=True,
                    created_at=utcnow(),
                    model_tag=tag,
                    publisher=publisher,
                    family=family,
                    parameter_size=params,
                    quantization=quant,
                    format="gguf",
                    license=lic,
                    context_length=ctx,
                    download_size_mb=dl,
                    min_ram_mb=ram,
                    min_disk_mb=disk,
                    min_vram_mb=0,
                    min_cpu_cores=cpu,
                    gpu_required=False,
                    requirements_estimated=True,
                )
            )
        await db.flush()
        m008 = _migration("008_model_artifacts.py")
        for spec in m008.NEW_MODELS:
            if not (await db.execute(select(Model).where(Model.id == spec["id"]))).scalar_one_or_none():
                db.add(Model(**spec, requirements_estimated=True, is_approved=True, created_at=utcnow()))
        await db.flush()
        existing = {a.id for a in (await db.execute(select(ModelArtifact))).scalars().all()}
        for model in (await db.execute(select(Model))).scalars().all():
            aid = m008.artifact_id(model.id, "ollama")
            if model.runtime == "ollama" and model.model_tag and aid not in existing:
                db.add(
                    ModelArtifact(
                        id=aid,
                        model_id=model.id,
                        runtime="ollama",
                        source_type="ollama",
                        reference=model.model_tag,
                        format="ollama",
                        quantization=model.quantization,
                        min_ram_mb=model.min_ram_mb,
                        min_disk_mb=model.min_disk_mb,
                        min_vram_mb=model.min_vram_mb or 0,
                        min_cpu_cores=model.min_cpu_cores or 1,
                        gpu_required=model.gpu_required,
                    )
                )
        for row in m008.hf_rows():
            if row["id"] not in existing:
                db.add(ModelArtifact(**row))
        await db.commit()
    print(f"Initialised {settings.DATABASE_URL}")


if __name__ == "__main__":
    asyncio.run(main())
