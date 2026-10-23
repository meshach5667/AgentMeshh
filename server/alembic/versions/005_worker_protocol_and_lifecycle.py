"""worker protocol, deployment lifecycle, reservations, API keys, request metering, Ollama catalog

Revision ID: 005
Revises: 004
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

# Old deployment statuses -> new lifecycle states (see app.services.deployment_lifecycle).
STATUS_MAP = {
    "VALIDATING": "REQUESTED",
    "SCHEDULING": "REQUESTED",
    "ASSIGNED": "SCHEDULED",
    "DEPLOYING": "PROVISIONING",
    "HEALTH_CHECK": "STARTING",
    "RUNNING": "READY",
}

# Curated Ollama models. Sizes are the published Ollama download sizes; RAM/disk figures are estimates
# (weights plus runtime and context overhead) and are flagged as such via requirements_estimated.
CATALOG = [
    # tag, name, publisher, family, params, quant, license, ctx, download_mb, ram_mb, disk_mb, cpu
    ("smollm2:135m", "SmolLM2 135M", "Hugging Face", "llama", "135M", "F16", "Apache-2.0", 8192, 271, 768, 512, 1),
    ("qwen2.5:0.5b", "Qwen2.5 0.5B", "Alibaba Qwen", "qwen2", "494M", "Q4_K_M", "Apache-2.0", 32768, 398, 1024, 768, 1),
    (
        "llama3.2:1b",
        "Llama 3.2 1B",
        "Meta",
        "llama",
        "1.2B",
        "Q8_0",
        "Llama 3.2 Community License",
        131072,
        1300,
        2048,
        1792,
        2,
    ),
    (
        "llama3.2:3b",
        "Llama 3.2 3B",
        "Meta",
        "llama",
        "3.2B",
        "Q4_K_M",
        "Llama 3.2 Community License",
        131072,
        2000,
        3072,
        2560,
        2,
    ),
    ("qwen2.5:7b", "Qwen2.5 7B", "Alibaba Qwen", "qwen2", "7.6B", "Q4_K_M", "Apache-2.0", 32768, 4700, 6144, 5632, 4),
    (
        "llama3.1:8b",
        "Llama 3.1 8B",
        "Meta",
        "llama",
        "8.0B",
        "Q4_K_M",
        "Llama 3.1 Community License",
        131072,
        4900,
        6656,
        5888,
        4,
    ),
]


def upgrade() -> None:
    # --- nodes: worker identity, provider-allocated capacity, reservations
    for col in [
        sa.Column("mode", sa.String(20), nullable=True),
        sa.Column("worker_version", sa.String(50), nullable=True),
        sa.Column("protocol_version", sa.Integer(), nullable=True),
        sa.Column("runtimes", JSON(), nullable=True),
        sa.Column("accepting_workloads", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_metrics", JSON(), nullable=True),
    ]:
        op.add_column("nodes", col)
    for name in [
        "allocated_cpu_cores",
        "allocated_ram_mb",
        "allocated_disk_mb",
        "allocated_vram_mb",
        "reserved_cpu_cores",
        "reserved_ram_mb",
        "reserved_disk_mb",
        "reserved_vram_mb",
    ]:
        op.add_column("nodes", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))

    # --- models: catalog metadata and scheduler requirements
    for col in [
        sa.Column("model_tag", sa.String(255), nullable=True),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("family", sa.String(100), nullable=True),
        sa.Column("parameter_size", sa.String(50), nullable=True),
        sa.Column("quantization", sa.String(50), nullable=True),
        sa.Column("format", sa.String(50), nullable=True),
        sa.Column("license", sa.String(255), nullable=True),
        sa.Column("context_length", sa.Integer(), nullable=True),
        sa.Column("download_size_mb", sa.Integer(), nullable=True),
        sa.Column("min_ram_mb", sa.Integer(), nullable=True),
        sa.Column("min_disk_mb", sa.Integer(), nullable=True),
        sa.Column("min_vram_mb", sa.Integer(), nullable=True),
        sa.Column("min_cpu_cores", sa.Integer(), nullable=True),
        sa.Column("gpu_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requirements_estimated", sa.Boolean(), nullable=False, server_default=sa.true()),
    ]:
        op.add_column("models", col)
    op.create_index("ix_models_model_tag", "models", ["model_tag"])

    # --- deployments: lifecycle details
    for col in [
        sa.Column("runtime", sa.String(50), nullable=True),
        sa.Column("model_tag", sa.String(255), nullable=True),
        sa.Column("model_digest", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("last_health_at", sa.DateTime(), nullable=True),
        sa.Column("was_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cleanup_status", sa.String(50), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    ]:
        op.add_column("deployments", col)
    op.create_unique_constraint(
        "uq_deployments_customer_idempotency", "deployments", ["customer_id", "idempotency_key"]
    )
    deployments = sa.table("deployments", sa.column("status", sa.String()))
    for old, new in STATUS_MAP.items():
        op.execute(deployments.update().where(deployments.c.status == old).values(status=new))

    op.create_table(
        "deployment_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id", ondelete="CASCADE")),
        sa.Column("from_status", sa.String(50), nullable=True),
        sa.Column("to_status", sa.String(50), nullable=True),
        sa.Column("actor", sa.String(50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_deployment_events_deployment_id", "deployment_events", ["deployment_id"])

    op.create_table(
        "node_enrollment_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_id", UUID(as_uuid=True), sa.ForeignKey("providers.id"), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_node_enrollment_tokens_provider_id", "node_enrollment_tokens", ["provider_id"])

    op.create_table(
        "node_commands",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("payload", JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_node_commands_node_id", "node_commands", ["node_id"])
    op.create_index("ix_node_commands_deployment_id", "node_commands", ["deployment_id"])
    op.create_index("ix_node_commands_status", "node_commands", ["status"])

    op.create_table(
        "resource_reservations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id"), nullable=False, unique=True),
        sa.Column("node_id", UUID(as_uuid=True), sa.ForeignKey("nodes.id"), nullable=False),
        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("ram_mb", sa.Integer(), nullable=False),
        sa.Column("disk_mb", sa.Integer(), nullable=False),
        sa.Column("vram_mb", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_resource_reservations_node_id", "resource_reservations", ["node_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("key_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("scopes", JSON(), nullable=False),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    # --- usage_records: per-request inference metering
    for col in [
        sa.Column("kind", sa.String(20), nullable=False, server_default="resource"),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("api_key_id", UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("endpoint", sa.String(100), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("token_source", sa.String(30), nullable=True),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
    ]:
        op.add_column("usage_records", col)
    op.create_unique_constraint("uq_usage_records_request_id", "usage_records", ["request_id"])

    # --- seed catalog
    models = sa.table(
        "models",
        *[
            sa.column(n, t)
            for n, t in [
                ("id", UUID(as_uuid=True)),
                ("name", sa.String()),
                ("version", sa.String()),
                ("runtime", sa.String()),
                ("source", sa.String()),
                ("is_approved", sa.Boolean()),
                ("created_at", sa.DateTime()),
                ("model_tag", sa.String()),
                ("publisher", sa.String()),
                ("family", sa.String()),
                ("parameter_size", sa.String()),
                ("quantization", sa.String()),
                ("format", sa.String()),
                ("license", sa.String()),
                ("context_length", sa.Integer()),
                ("download_size_mb", sa.Integer()),
                ("min_ram_mb", sa.Integer()),
                ("min_disk_mb", sa.Integer()),
                ("min_vram_mb", sa.Integer()),
                ("min_cpu_cores", sa.Integer()),
                ("gpu_required", sa.Boolean()),
                ("requirements_estimated", sa.Boolean()),
            ]
        ],
    )
    now = datetime.utcnow()
    op.bulk_insert(
        models,
        [
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"agentmesh:ollama:{tag}"),
                "name": name,
                "version": tag.split(":", 1)[1],
                "runtime": "ollama",
                "source": "ollama-registry",
                "is_approved": True,
                "created_at": now,
                "model_tag": tag,
                "publisher": publisher,
                "family": family,
                "parameter_size": params,
                "quantization": quant,
                "format": "gguf",
                "license": license_,
                "context_length": ctx,
                "download_size_mb": dl,
                "min_ram_mb": ram,
                "min_disk_mb": disk,
                "min_vram_mb": 0,
                "min_cpu_cores": cpu,
                "gpu_required": False,
                "requirements_estimated": True,
            }
            for (tag, name, publisher, family, params, quant, license_, ctx, dl, ram, disk, cpu) in CATALOG
        ],
    )


def downgrade() -> None:
    models = sa.table("models", sa.column("id", UUID(as_uuid=True)))
    ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"agentmesh:ollama:{row[0]}") for row in CATALOG]
    op.execute(models.delete().where(models.c.id.in_(ids)))

    op.drop_constraint("uq_usage_records_request_id", "usage_records", type_="unique")
    for name in [
        "response_bytes",
        "token_source",
        "output_tokens",
        "input_tokens",
        "duration_ms",
        "outcome",
        "status_code",
        "endpoint",
        "api_key_id",
        "request_id",
        "kind",
    ]:
        op.drop_column("usage_records", name)

    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_resource_reservations_node_id", table_name="resource_reservations")
    op.drop_table("resource_reservations")
    for ix in ["ix_node_commands_status", "ix_node_commands_deployment_id", "ix_node_commands_node_id"]:
        op.drop_index(ix, table_name="node_commands")
    op.drop_table("node_commands")
    op.drop_index("ix_node_enrollment_tokens_provider_id", table_name="node_enrollment_tokens")
    op.drop_table("node_enrollment_tokens")
    op.drop_index("ix_deployment_events_deployment_id", table_name="deployment_events")
    op.drop_table("deployment_events")

    deployments = sa.table("deployments", sa.column("status", sa.String()))
    for old, new in [
        ("READY", "RUNNING"),
        ("PROVISIONING", "DEPLOYING"),
        ("STARTING", "HEALTH_CHECK"),
        ("SCHEDULED", "ASSIGNED"),
        ("UNHEALTHY", "RUNNING"),
        ("CANCELLED", "STOPPED"),
    ]:
        op.execute(deployments.update().where(deployments.c.status == old).values(status=new))
    op.drop_constraint("uq_deployments_customer_idempotency", "deployments", type_="unique")
    for name in [
        "updated_at",
        "deleted_at",
        "cleanup_status",
        "was_ready",
        "last_health_at",
        "ready_at",
        "error_message",
        "error_code",
        "idempotency_key",
        "model_digest",
        "model_tag",
        "runtime",
    ]:
        op.drop_column("deployments", name)

    op.drop_index("ix_models_model_tag", table_name="models")
    for name in [
        "requirements_estimated",
        "gpu_required",
        "min_cpu_cores",
        "min_vram_mb",
        "min_disk_mb",
        "min_ram_mb",
        "download_size_mb",
        "context_length",
        "license",
        "format",
        "quantization",
        "parameter_size",
        "family",
        "publisher",
        "model_tag",
    ]:
        op.drop_column("models", name)

    for name in [
        "reserved_vram_mb",
        "reserved_disk_mb",
        "reserved_ram_mb",
        "reserved_cpu_cores",
        "allocated_vram_mb",
        "allocated_disk_mb",
        "allocated_ram_mb",
        "allocated_cpu_cores",
        "last_metrics",
        "accepting_workloads",
        "runtimes",
        "protocol_version",
        "worker_version",
        "mode",
    ]:
        op.drop_column("nodes", name)
