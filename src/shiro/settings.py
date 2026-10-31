"""Configuração do SHIRO.

A configuração vem de duas fontes, nesta ordem de prioridade:

1. variáveis de ambiente com prefixo ``SHIRO_`` e ``__`` entre seções
   (ex.: ``SHIRO_AGENT__MAX_STEPS=4``);
2. o arquivo ``shiro.toml`` (ver ``config/shiro.example.toml``).

Tudo tem valor padrão seguro, então o SHIRO funciona sem arquivo nenhum.
Chaves desconhecidas são rejeitadas para que erros de digitação não passem
em silêncio. Segredos **nunca** ficam aqui: eles vão para o Gerenciador de
Credenciais do Windows.
"""

from __future__ import annotations

import ipaddress
import re
import tomllib
from datetime import time
from pathlib import Path
from typing import Annotated, Any, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from shiro import paths

RiskLevel = Literal["R0", "R1", "R2", "R3", "R4"]
CloudProvider = Literal["gemini", "anthropic", "openai"]


class ConfigError(Exception):
    """A configuração não pôde ser lida ou é inválida."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneralSettings(_Section):
    assistant_name: str = Field(default="Shiro", min_length=1)
    language: str = "pt-BR"
    timezone: str = "America/Sao_Paulo"
    city: str = ""  # cidade padrão do clima; fica só no shiro.toml local

    @field_validator("timezone")
    @classmethod
    def _timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            msg = f"fuso horário desconhecido: {value!r}"
            raise ValueError(msg) from exc
        return value


class AgentSettings(_Section):
    max_steps: int = Field(default=8, ge=1, le=32)
    step_timeout_s: float = Field(default=20.0, gt=0)
    turn_timeout_s: float = Field(default=60.0, gt=0)
    max_history_messages: int = Field(default=8, ge=0, le=32)

    @model_validator(mode="after")
    def _turn_covers_step(self) -> Self:
        if self.turn_timeout_s < self.step_timeout_s:
            msg = "turn_timeout_s precisa ser maior ou igual a step_timeout_s"
            raise ValueError(msg)
        return self


class RouterSettings(_Section):
    escalate_on_validation_failure: bool = True
    cloud_triggers: tuple[str, ...] = ("pensa bem", "pesquisa", "analisa com calma")


class LocalLLMSettings(_Section):
    provider: Literal["ollama"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:4b-instruct"  # provisório; ver ADR-0010
    num_ctx: int = Field(default=4096, ge=1024)
    # Camadas do modelo na GPU: 99 = todas, 0 = só CPU. O cálculo automático do Ollama
    # é conservador e deixava ~1/3 do modelo na CPU em placas de 4 GB (ADR-0010).
    num_gpu: int = Field(default=99, ge=0)
    keep_alive: str = "30m"  # ADR-0011


class CloudLLMSettings(_Section):
    provider: CloudProvider = "gemini"
    model: str = ""
    fallback: tuple[CloudProvider, ...] = ("anthropic", "openai")
    daily_budget_usd: float = Field(default=0.5, ge=0)
    rpm_limit: int = Field(default=5, ge=1)


class LLMSettings(_Section):
    local: LocalLLMSettings = LocalLLMSettings()
    cloud: CloudLLMSettings = CloudLLMSettings()


class STTSettings(_Section):
    engine: Literal["faster-whisper"] = "faster-whisper"
    model: str = "small"
    device: Literal["cuda", "cpu"] = "cpu"  # a GPU fica para o LLM (ADR-0010)
    compute_type: str = "int8"
    language: str = "pt"


class TTSSettings(_Section):
    engine: Literal["piper"] = "piper"
    voice: str = "pt_BR-faber-medium"
    length_scale: float = Field(default=1.0, gt=0)


class WakeWordSettings(_Section):
    engine: Literal["openwakeword"] = "openwakeword"
    model_path: str = ""
    threshold: float = Field(default=0.5, gt=0, lt=1)
    follow_up_window_s: float = Field(default=5.0, ge=0)


class VoiceSettings(_Section):
    enabled: bool = True
    activation: Literal["push_to_talk", "wake_word", "both"] = "push_to_talk"
    push_to_talk_hotkey: str = "ctrl+alt+space"
    input_device: str = "default"
    output_device: str = "default"
    stt: STTSettings = STTSettings()
    tts: TTSSettings = TTSSettings()
    wake_word: WakeWordSettings = WakeWordSettings()


class AppEntry(_Section):
    """Um app que o SHIRO pode abrir e fechar."""

    launch: str = Field(min_length=1)  # caminho, comando do PATH ou URI (ex.: "spotify:")
    process: str = ""  # nome do processo para fechar (ex.: "Spotify.exe")
    name: str = ""  # como o SHIRO fala o nome (ex.: "VS Code")
    aliases: tuple[str, ...] = ()  # outros nomes falados (ex.: ["vs code", "code"])

    @property
    def label(self) -> str:
        return self.name or self.launch

    @property
    def process_name(self) -> str:
        if self.process:
            return self.process
        base = self.launch.replace("\\", "/").rsplit("/", 1)[-1]
        return base if base.casefold().endswith(".exe") else ""


def _apps_from_strings(value: Any) -> Any:
    """Aceita ``spotify = "spotify:"`` como atalho para ``{launch = "spotify:"}``."""
    if isinstance(value, dict):
        return {
            key: {"launch": item} if isinstance(item, str) else item
            for key, item in value.items()  # pyright: ignore[reportUnknownVariableType]
        }
    return value


class EmergencySettings(_Section):
    hotkey: str = "ctrl+alt+shift+s"


class PolicySettings(_Section):
    read_only_mode: bool = True
    batch_confirm_threshold: int = Field(default=5, ge=1)
    confirmation_timeout_s: float = Field(default=30.0, gt=0)
    allowed_folders: tuple[str, ...] = ()
    allowed_apps: Annotated[dict[str, AppEntry], BeforeValidator(_apps_from_strings)] = Field(
        default_factory=dict[str, AppEntry]
    )
    emergency: EmergencySettings = EmergencySettings()

    @field_validator("allowed_apps")
    @classmethod
    def _app_keys_are_identifiers(cls, value: dict[str, AppEntry]) -> dict[str, AppEntry]:
        for key in value:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                msg = f"nome de app inválido: {key!r} (use minúsculas, números e _)"
                raise ValueError(msg)
        return value


class ActivitiesSettings(_Section):
    default_due_time: time = time(23, 59)
    alert_offsets: tuple[str, ...] = ("1d", "2h")
    local_only: bool = True

    @field_validator("alert_offsets")
    @classmethod
    def _offsets_are_durations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            amount, unit = item[:-1], item[-1:]
            if not amount.isdigit() or int(amount) == 0 or unit not in {"m", "h", "d"}:
                msg = f"alerta inválido: {item!r} (use, por exemplo, '30m', '2h' ou '1d')"
                raise ValueError(msg)
        return value


class MemorySettings(_Section):
    embedding_model: str = "nomic-embed-text"
    default_local_only: bool = True


class RetentionSettings(_Section):
    messages_days: int = Field(default=90, ge=1)
    trash_days: int = Field(default=7, ge=1)
    audit_days: int = Field(default=365, ge=1)

    @model_validator(mode="after")
    def _audit_outlives_messages(self) -> Self:
        if self.audit_days < self.messages_days:
            msg = "audit_days não pode ser menor que messages_days (ver docs/04-modelo-de-dados.md)"
            raise ValueError(msg)
        return self


class ApiSettings(_Section):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # Ameaça A-05: a API local nunca pode escutar na rede.
        if value == "localhost":
            return value
        try:
            is_loopback = ipaddress.ip_address(value).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            msg = "a API local só pode escutar em 127.0.0.1, ::1 ou localhost"
            raise ValueError(msg)
        return value


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_file_mb: int = Field(default=10, ge=1)
    backups: int = Field(default=5, ge=1)


class McpServerSettings(_Section):
    url: str
    default_risk: RiskLevel = "R2"


class McpSettings(_Section):
    servers: dict[str, McpServerSettings] = Field(default_factory=dict[str, McpServerSettings])


class Settings(BaseSettings):
    """Configuração completa e imutável do SHIRO."""

    model_config = SettingsConfigDict(
        env_prefix="SHIRO_",
        env_nested_delimiter="__",
        extra="forbid",
        frozen=True,
    )

    general: GeneralSettings = GeneralSettings()
    agent: AgentSettings = AgentSettings()
    router: RouterSettings = RouterSettings()
    llm: LLMSettings = LLMSettings()
    voice: VoiceSettings = VoiceSettings()
    policy: PolicySettings = PolicySettings()
    activities: ActivitiesSettings = ActivitiesSettings()
    memory: MemorySettings = MemorySettings()
    retention: RetentionSettings = RetentionSettings()
    api: ApiSettings = ApiSettings()
    logging: LoggingSettings = LoggingSettings()
    mcp: McpSettings = McpSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Ambiente vence o arquivo; .env e secrets em arquivo não são usados de propósito.
        return (env_settings, init_settings)


def read_config_file(path: Path) -> dict[str, Any]:
    """Lê o TOML; arquivo ausente equivale a configuração vazia."""
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        msg = f"{path}: TOML inválido ({exc})"
        raise ConfigError(msg) from exc


def load_settings(path: Path | None = None) -> Settings:
    """Carrega e valida a configuração.

    Raises:
        ConfigError: se o arquivo não for TOML válido ou algum valor for inválido.
    """
    config_path = path if path is not None else paths.config_file()
    data = read_config_file(config_path)
    try:
        return Settings(**data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        msg = f"{config_path}: configuração inválida ({problems})"
        raise ConfigError(msg) from exc
