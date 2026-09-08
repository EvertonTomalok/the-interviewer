"""Settings: the full shape of PRD §6. No module reads `os.environ` directly.

`pydantic-settings` is allowed inside `packages/core` alongside `pydantic`
-- see this package's `CONTEXT.md` and `docs/adr/0002-core-logging-without-structlog.md`
for the boundary this sits on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from interviewer_core.errors import ConfigError


class ProviderCreds(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


class LLMCreds(BaseModel):
    openrouter: ProviderCreds = ProviderCreds()
    openai_compat: ProviderCreds = ProviderCreds()


class SpeechCreds(BaseModel):
    openai_compat: ProviderCreds = ProviderCreds()


class LocalFsCreds(BaseModel):
    root: str = "./var/blobs"


class GcsCreds(BaseModel):
    bucket: str | None = None
    credentials_json: str | None = None


class S3Creds(BaseModel):
    bucket: str | None = None
    region: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    endpoint_url: str | None = None


class StorageCreds(BaseModel):
    local_fs: LocalFsCreds = LocalFsCreds()
    gcs: GcsCreds = GcsCreds()
    s3: S3Creds = S3Creds()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    database_url: str
    redis_url: str

    # --- Auth ---------------------------------------------------------
    auth_secret_key: str = ""
    access_token_ttl_minutes: int = 60
    registration_open: bool = False
    public_base_url: str = "http://localhost:8000"
    invite_ttl_hours: int = 168
    candidate_token_ttl_minutes: int = 120
    passkey_max_attempts: int = 5
    passkey_lockout_minutes: int = 15

    # --- LLM ------------------------------------------------------------
    llm_provider: str = "fake"
    llm_model: str = "openai/gpt-4.1-mini"
    llm_temperature: float = 0.4
    llm_max_tokens: int = 800
    llm_timeout_seconds: int = 60
    llm: LLMCreds = LLMCreds()

    # --- Speech -----------------------------------------------------------
    stt_provider: str = "fake"
    stt_model: str = ""
    stt_language: str = ""
    stt: SpeechCreds = SpeechCreds()

    reply_mode: Literal["text", "voice"] = "text"
    tts_provider: str = "none"
    tts_model: str = ""
    tts_voice: str = ""
    tts: SpeechCreds = SpeechCreds()

    # --- Infrastructure adapters -------------------------------------------
    storage_provider: str = "local_fs"
    storage: StorageCreds = StorageCreds()

    workflow_provider: str = "redis"
    workflow_visibility_timeout_seconds: int = 120
    workflow_max_attempts: int = 3

    # --- Upload guards -------------------------------------------------
    upload_max_bytes: int = 26_214_400
    upload_max_seconds: int = 300
    upload_allowed_mime: str = "audio/webm,audio/ogg,audio/wav,audio/mpeg"
    session_max_turns: int = 40

    @property
    def upload_allowed_mime_types(self) -> tuple[str, ...]:
        return tuple(m.strip() for m in self.upload_allowed_mime.split(",") if m.strip())


def load_settings() -> Settings:
    """Construct `Settings`, converting a missing/invalid field into a
    `ConfigError` that names it, and enforcing the one cross-field rule."""
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing = ", ".join(
            "__".join(str(part) for part in error["loc"]).upper() for error in exc.errors()
        )
        raise ConfigError(f"missing or invalid setting(s): {missing}") from exc

    if settings.reply_mode == "voice" and settings.tts_provider == "none":
        raise ConfigError(
            "REPLY_MODE=voice requires a real TTS_PROVIDER; TTS_PROVIDER=none "
            "would silently answer in text"
        )

    return settings
