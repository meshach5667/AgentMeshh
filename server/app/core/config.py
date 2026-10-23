import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

INSECURE_DEFAULT_SECRET = "supersecretkey"
DEV_ENVIRONMENTS = {"dev", "development", "test", "testing"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[3] / ".env"),
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+asyncpg://agentmesh:agentmesh@localhost:5432/agentmesh"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = INSECURE_DEFAULT_SECRET
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    HEARTBEAT_TIMEOUT_SECONDS: int = 90
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "dev"
    LOG_LEVEL: str = "INFO"
    # Explicit origins only: credentials are allowed, so a wildcard would be unsafe.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    # Unpaid "test credits" for local development. Never honoured outside dev/test environments.
    ALLOW_TEST_CREDITS: bool = True
    SQL_ECHO: bool = False
    LOG_JSON: bool = True

    # Public base URL customers use to reach the gateway (used to build deployment endpoints).
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Worker protocol
    WORKER_PROTOCOL_VERSIONS: list[int] = [1]
    WORKER_HEARTBEAT_INTERVAL_SECONDS: int = 15
    ENROLLMENT_TOKEN_TTL_MINUTES: int = 60
    COMMAND_LEASE_SECONDS: int = 60
    COMMAND_MAX_ATTEMPTS: int = 3
    WORKER_MAX_BODY_BYTES: int = 256 * 1024
    # Directory holding manifest.json, manifest.sig and the release wheel (see scripts/sign_worker_release.py).
    # The control plane only serves these files; workers verify the signature with their pinned key.
    WORKER_RELEASE_DIR: str = ""

    # Deployment lifecycle timeouts
    PROVISION_STALL_TIMEOUT_SECONDS: int = 900  # no progress report for this long -> FAILED
    PROVISION_MAX_SECONDS: int = 3600
    STOP_TIMEOUT_SECONDS: int = 300
    UNHEALTHY_GRACE_SECONDS: int = 180  # unhealthy this long -> move to another node (or fail)
    MAX_SCHEDULE_ATTEMPTS: int = 3  # placements per deployment, including the first
    MONITOR_INTERVAL_SECONDS: int = 15
    BACKGROUND_JOBS_ENABLED: bool = True
    MIGRATE_ON_STARTUP: bool = True

    # Multi-replica coordination: "memory" (single API process) or "redis" (shared limits and tunnel routing)
    COORDINATION_BACKEND: str = "memory"

    # Inference gateway
    GATEWAY_MAX_BODY_BYTES: int = 1024 * 1024
    GATEWAY_RATE_LIMIT_PER_MINUTE: int = 60
    # Login and registration attempts per minute, per client address and per email address.
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    GATEWAY_MAX_CONCURRENT_PER_DEPLOYMENT: int = 4
    GATEWAY_FIRST_BYTE_TIMEOUT_SECONDS: int = 180
    GATEWAY_IDLE_TIMEOUT_SECONDS: int = 120
    GATEWAY_MAX_RESPONSE_BYTES: int = 32 * 1024 * 1024

    # Billing. One platform currency; wallets, prices, top-ups and payouts all use it.
    BILLING_CURRENCY: str = "NGN"
    BILLING_INTERVAL_SECONDS: int = 300  # how often READY time and tokens are rated into charges
    # A deployment needs enough balance for this many hours of its reserved resources at current prices.
    BILLING_MIN_PREPAID_HOURS: float = 1.0

    # Paystack (https://paystack.com/docs/api). Test-mode keys (sk_test_...) unless PAYSTACK_ALLOW_LIVE.
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    PAYSTACK_ALLOW_LIVE: bool = False
    PAYSTACK_TIMEOUT_SECONDS: float = 20.0
    # Paystack's webhook source addresses; empty disables the check (e.g. behind a proxy that rewrites IPs).
    PAYSTACK_WEBHOOK_IPS: list[str] = []
    # Where Paystack sends the customer after checkout (the dashboard verifies the reference on return).
    FRONTEND_URL: str = "http://localhost:3000"
    TOPUP_MIN_AMOUNT: Decimal = Decimal("100")
    TOPUP_MAX_AMOUNT: Decimal = Decimal("1000000")
    PAYOUT_MIN_AMOUNT: Decimal = Decimal("1000")
    PAYOUTS_REQUIRE_APPROVAL: bool = True
    # Payments/payouts still unresolved after this long are checked against Paystack by reconciliation.
    RECONCILE_AFTER_MINUTES: int = 30

    # Bearer token for GET /metrics. Empty disables the endpoint.
    METRICS_TOKEN: str = ""

    # AI deployment agent. Inference runs on an internal machine (e.g. a laptop running Ollama) whose adapter
    # connects outbound and pulls requests from a queue here (see docs/AI_INFERENCE_SETUP.md); the control
    # plane never connects to Ollama. Empty AI_INFERENCE_TOKEN disables the adapter endpoints.
    AI_INFERENCE_TOKEN: str = ""
    # The model every adapter must serve. Requests are never answered by a different model.
    OLLAMA_MODEL: str = "gemma4:e2b-it-qat"
    AI_REQUEST_TIMEOUT: int = 180  # lease on one inference request; an unanswered lease is retried
    AI_MAX_CONCURRENT_REQUESTS: int = 1  # requests leased at once across all inference machines
    AI_MAX_ATTEMPTS: int = 2  # deliveries per inference request
    AI_QUEUE_MAX_LENGTH: int = 20  # waiting + in-flight inference requests; new AI work is refused beyond this
    AI_QUEUE_TTL_SECONDS: int = 3600  # queued requests expire (e.g. the inference machine stayed offline)
    AI_NUM_CTX: int = 4096
    AI_MAX_TOKENS: int = 512
    AI_RATE_LIMIT_PER_MINUTE: int = 3  # new AI deployment requests per user
    AI_NODE_TIMEOUT_SECONDS: int = 45  # no adapter heartbeat for this long -> AI service unavailable
    AI_MAX_AGENT_STEPS: int = 6  # model turns per planning or diagnosis conversation
    AI_MAX_TOOL_CALLS: int = 8  # tool calls per AI deployment run, all purposes
    # Platform ceilings on what a customer may authorize for autonomous deployments.
    AI_MAX_DEPLOYMENT_HOURS: int = 168
    AI_MAX_RECOVERY_ATTEMPTS: int = 3

    # Community models: customers import public GGUF files from Hugging Face for their own use. They are
    # private to the importer, unreviewed, and only placed on nodes whose provider opted in.
    COMMUNITY_MODELS_ENABLED: bool = True
    COMMUNITY_MODEL_MAX_BYTES: int = 16 * 2**30
    COMMUNITY_MODELS_PER_CUSTOMER: int = 20
    COMMUNITY_MODEL_IMPORTS_PER_MINUTE: int = 5
    HUGGINGFACE_URL: str = "https://huggingface.co"

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_async_driver(cls, url: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs; the engine needs the asyncpg driver.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+asyncpg://" + url[len(prefix) :]
        return url.replace("sslmode=", "ssl=")

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                origins = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("CORS_ORIGINS must be a JSON array or comma-separated origins") from exc
            if not isinstance(origins, list):
                raise ValueError("CORS_ORIGINS JSON value must be an array")
            return origins

        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def is_dev(self) -> bool:
        return self.ENVIRONMENT.lower() in DEV_ENVIRONMENTS

    @property
    def test_credits_enabled(self) -> bool:
        return self.is_dev and self.ALLOW_TEST_CREDITS

    @property
    def payments_enabled(self) -> bool:
        return bool(self.PAYSTACK_SECRET_KEY)

    @property
    def payments_mode(self) -> str | None:
        if not self.PAYSTACK_SECRET_KEY:
            return None
        return "live" if self.PAYSTACK_SECRET_KEY.startswith("sk_live_") else "test"

    @model_validator(mode="after")
    def _check_heartbeat_timing(self) -> "Settings":
        # Workers heartbeat at the interval the control plane gives them. A timeout shorter than a few
        # intervals marks healthy nodes offline and moves their deployments away.
        if self.HEARTBEAT_TIMEOUT_SECONDS < 3 * self.WORKER_HEARTBEAT_INTERVAL_SECONDS:
            raise ValueError(
                "HEARTBEAT_TIMEOUT_SECONDS must be at least 3x WORKER_HEARTBEAT_INTERVAL_SECONDS "
                f"(got {self.HEARTBEAT_TIMEOUT_SECONDS}s vs {self.WORKER_HEARTBEAT_INTERVAL_SECONDS}s)"
            )
        return self

    @model_validator(mode="after")
    def _check_production_safety(self) -> "Settings":
        if not self.is_dev:
            if (
                self.SECRET_KEY in (INSECURE_DEFAULT_SECRET, "your-secret-key-change-in-production")
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters outside dev/test")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must not contain '*' outside dev/test")
            if not self.CORS_ORIGINS:
                raise ValueError("CORS_ORIGINS must include at least one frontend origin outside dev/test")
            if not self.PUBLIC_BASE_URL.startswith("https://"):
                raise ValueError("PUBLIC_BASE_URL must use https outside dev/test (API keys travel in headers)")
            if self.AI_INFERENCE_TOKEN and len(self.AI_INFERENCE_TOKEN) < 32:
                raise ValueError("AI_INFERENCE_TOKEN must be a random value of at least 32 characters outside dev/test")
        return self

    @model_validator(mode="after")
    def _check_ai(self) -> "Settings":
        if not 1 <= self.AI_MAX_CONCURRENT_REQUESTS <= 16:
            raise ValueError("AI_MAX_CONCURRENT_REQUESTS must be between 1 and 16")
        if not 1 <= self.AI_QUEUE_MAX_LENGTH <= 1000:
            raise ValueError("AI_QUEUE_MAX_LENGTH must be between 1 and 1000")
        if not 1024 <= self.AI_NUM_CTX <= 32768 or not 64 <= self.AI_MAX_TOKENS <= 4096:
            raise ValueError("AI_NUM_CTX must be 1024-32768 and AI_MAX_TOKENS 64-4096")
        if self.AI_REQUEST_TIMEOUT < 10 or self.AI_MAX_ATTEMPTS < 1:
            raise ValueError("AI_REQUEST_TIMEOUT must be at least 10 seconds and AI_MAX_ATTEMPTS at least 1")
        return self

    @model_validator(mode="after")
    def _check_payments(self) -> "Settings":
        key = self.PAYSTACK_SECRET_KEY
        if key and not key.startswith(("sk_test_", "sk_live_")):
            raise ValueError("PAYSTACK_SECRET_KEY must be a Paystack secret key (sk_test_... or sk_live_...)")
        if key.startswith("sk_live_") and not self.PAYSTACK_ALLOW_LIVE:
            raise ValueError("A live Paystack key needs PAYSTACK_ALLOW_LIVE=true (payments default to test mode)")
        if len(self.BILLING_CURRENCY) != 3 or not self.BILLING_CURRENCY.isupper():
            raise ValueError("BILLING_CURRENCY must be an ISO 4217 code such as NGN")
        return self


settings = Settings()
