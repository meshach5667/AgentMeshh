"""model artifacts: explicit model <-> runtime compatibility with pinned sources (llama.cpp, vLLM)

Every existing Ollama catalog entry becomes an "ollama" artifact. Hugging Face artifacts are pinned to a
commit; GGUF files also carry their SHA-256 and size (fetched from the Hugging Face API on 2026-10-20).
Requirement figures are estimates.

Revision ID: 008
Revises: 007
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def model_id(tag: str) -> uuid.UUID:
    """Ids of the models seeded by migration 005."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"agentmesh:ollama:{tag}")


QWEN15_MODEL_ID = uuid.uuid5(uuid.NAMESPACE_URL, "agentmesh:model:qwen2.5-1.5b-instruct")

NEW_MODELS = [
    {
        "id": QWEN15_MODEL_ID,
        "name": "Qwen2.5 1.5B Instruct",
        "version": "1.5b",
        "runtime": "vllm",
        "source": "huggingface",
        "model_tag": "Qwen/Qwen2.5-1.5B-Instruct",
        "publisher": "Alibaba Qwen",
        "family": "qwen2",
        "parameter_size": "1.5B",
        "quantization": "BF16",
        "format": "safetensors",
        "license": "Apache-2.0",
        "context_length": 32768,
        "download_size_mb": 2955,
        "min_ram_mb": 8192,
        "min_disk_mb": 4096,
        "min_vram_mb": 8192,
        "min_cpu_cores": 2,
        "gpu_required": True,
    },
]

# runtime, model id, reference, revision, file, sha256, size bytes, format, quant, ram, disk, vram, cpu, gpu
HF_ARTIFACTS = [
    (
        "llamacpp",
        model_id("smollm2:135m"),
        "bartowski/SmolLM2-135M-Instruct-GGUF",
        "09816acd5d99df7be770d85ea30822623dab342c",
        "SmolLM2-135M-Instruct-Q8_0.gguf",
        "5a1395716f7913741cc51d98581b9b1228d80987a9f7d3664106742eb06bba83",
        144811360,
        "gguf",
        "Q8_0",
        512,
        256,
        0,
        1,
        False,
    ),
    (
        "llamacpp",
        model_id("qwen2.5:0.5b"),
        "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "9217f5db79a29953eb74d5343926648285ec7e67",
        "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db",
        491400032,
        "gguf",
        "Q4_K_M",
        1024,
        640,
        0,
        1,
        False,
    ),
    (
        "vllm",
        model_id("qwen2.5:0.5b"),
        "Qwen/Qwen2.5-0.5B-Instruct",
        "7ae557604adf67be50417f59c2c2f167def9a775",
        None,
        None,
        953 * 2**20,
        "safetensors",
        "BF16",
        4096,
        2048,
        4096,
        2,
        True,
    ),
    (
        "vllm",
        QWEN15_MODEL_ID,
        "Qwen/Qwen2.5-1.5B-Instruct",
        "989aa7980e4cf806f80c7fef2b1adb7bc71aa306",
        None,
        None,
        2955 * 2**20,
        "safetensors",
        "BF16",
        8192,
        4096,
        8192,
        2,
        True,
    ),
]


def artifact_id(model: uuid.UUID, runtime: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"agentmesh:artifact:{model}:{runtime}")


def hf_rows() -> list[dict]:
    now = datetime(2026, 10, 20)
    return [
        {
            "id": artifact_id(mid, rt),
            "model_id": mid,
            "runtime": rt,
            "source_type": "huggingface",
            "reference": ref,
            "revision": rev,
            "file": file,
            "sha256": sha,
            "size_bytes": size,
            "format": fmt,
            "quantization": quant,
            "min_ram_mb": ram,
            "min_disk_mb": disk,
            "min_vram_mb": vram,
            "min_cpu_cores": cpu,
            "gpu_required": gpu,
            "requirements_estimated": True,
            "is_enabled": True,
            "created_at": now,
        }
        for (rt, mid, ref, rev, file, sha, size, fmt, quant, ram, disk, vram, cpu, gpu) in HF_ARTIFACTS
    ]


artifacts_table = sa.table(
    "model_artifacts",
    *[
        sa.column(n, t)
        for n, t in [
            ("id", UUID(as_uuid=True)),
            ("model_id", UUID(as_uuid=True)),
            ("runtime", sa.String()),
            ("source_type", sa.String()),
            ("reference", sa.String()),
            ("revision", sa.String()),
            ("file", sa.String()),
            ("sha256", sa.String()),
            ("size_bytes", sa.BigInteger()),
            ("format", sa.String()),
            ("quantization", sa.String()),
            ("min_ram_mb", sa.Integer()),
            ("min_disk_mb", sa.Integer()),
            ("min_vram_mb", sa.Integer()),
            ("min_cpu_cores", sa.Integer()),
            ("gpu_required", sa.Boolean()),
            ("requirements_estimated", sa.Boolean()),
            ("is_enabled", sa.Boolean()),
            ("created_at", sa.DateTime()),
        ]
    ],
)


def _literal(column: str, value):
    """SQL literal that also renders in offline mode (alembic upgrade --sql)."""
    if value is None:
        return sa.null()
    if isinstance(value, uuid.UUID):
        return sa.cast(sa.literal(str(value)), UUID(as_uuid=True))
    if isinstance(value, datetime):
        return sa.func.now()
    return sa.literal(value, type_=artifacts_table.c[column].type)


def upgrade() -> None:
    op.create_table(
        "model_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("model_id", UUID(as_uuid=True), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("runtime", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(255), nullable=False),
        sa.Column("revision", sa.String(64), nullable=True),
        sa.Column("file", sa.String(255), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("format", sa.String(20), nullable=True),
        sa.Column("quantization", sa.String(50), nullable=True),
        sa.Column("min_ram_mb", sa.Integer(), nullable=False),
        sa.Column("min_disk_mb", sa.Integer(), nullable=False),
        sa.Column("min_vram_mb", sa.Integer(), nullable=False),
        sa.Column("min_cpu_cores", sa.Integer(), nullable=False),
        sa.Column("gpu_required", sa.Boolean(), nullable=False),
        sa.Column("requirements_estimated", sa.Boolean(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_ready_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("model_id", "runtime", name="uq_model_artifacts_model_runtime"),
    )
    op.create_index("ix_model_artifacts_model_id", "model_artifacts", ["model_id"])

    now = datetime(2026, 10, 20)
    # Pure SQL so the migration also renders offline (alembic upgrade --sql).
    op.execute(
        """
        INSERT INTO model_artifacts (id, model_id, runtime, source_type, reference, size_bytes, format, quantization,
            min_ram_mb, min_disk_mb, min_vram_mb, min_cpu_cores, gpu_required, requirements_estimated, is_enabled,
            created_at)
        SELECT gen_random_uuid(), id, 'ollama', 'ollama', model_tag, download_size_mb::bigint * 1048576, 'ollama',
            quantization, min_ram_mb, min_disk_mb, COALESCE(min_vram_mb, 0), COALESCE(min_cpu_cores, 1),
            COALESCE(gpu_required, false), true, true, now()
        FROM models
        WHERE runtime = 'ollama' AND model_tag IS NOT NULL AND min_ram_mb IS NOT NULL AND min_disk_mb IS NOT NULL
        """
    )

    types = {
        "id": UUID(as_uuid=True),
        "created_at": sa.DateTime(),
        "context_length": sa.Integer(),
        "download_size_mb": sa.Integer(),
        "min_ram_mb": sa.Integer(),
        "min_disk_mb": sa.Integer(),
        "min_vram_mb": sa.Integer(),
        "min_cpu_cores": sa.Integer(),
        "gpu_required": sa.Boolean(),
        "requirements_estimated": sa.Boolean(),
        "is_approved": sa.Boolean(),
    }
    model_cols = sa.table(
        "models",
        *[
            sa.column(n, types.get(n, sa.String()))
            for n in (
                "id",
                "name",
                "version",
                "runtime",
                "source",
                "model_tag",
                "publisher",
                "family",
                "parameter_size",
                "quantization",
                "format",
                "license",
                "context_length",
                "download_size_mb",
                "min_ram_mb",
                "min_disk_mb",
                "min_vram_mb",
                "min_cpu_cores",
                "gpu_required",
                "requirements_estimated",
                "is_approved",
                "created_at",
            )
        ],
    )
    op.bulk_insert(
        model_cols, [m | {"requirements_estimated": True, "is_approved": True, "created_at": now} for m in NEW_MODELS]
    )
    # Hugging Face artifacts only for models that exist (they come from migration 005's catalog).
    models = sa.table("models", sa.column("id", UUID(as_uuid=True)))
    for row in hf_rows():
        cols = list(row)
        values = sa.select(*[_literal(c, row[c]) for c in cols]).where(
            sa.exists().where(models.c.id == _literal("model_id", row["model_id"]))
        )
        op.execute(artifacts_table.insert().from_select(cols, values))

    op.add_column(
        "deployments",
        sa.Column("artifact_id", UUID(as_uuid=True), sa.ForeignKey("model_artifacts.id"), nullable=True),
    )
    op.execute(
        "UPDATE deployments SET artifact_id = (SELECT a.id FROM model_artifacts a "
        "WHERE a.model_id = deployments.model_id AND a.runtime = deployments.runtime) WHERE runtime IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("deployments", "artifact_id")
    op.drop_index("ix_model_artifacts_model_id", table_name="model_artifacts")
    op.drop_table("model_artifacts")
    models = sa.table("models", sa.column("id", UUID(as_uuid=True)))
    op.execute(models.delete().where(models.c.id.in_([m["id"] for m in NEW_MODELS])))
