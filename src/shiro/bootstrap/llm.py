"""Montagem dos modelos: o local (Ollama) e a cadeia da nuvem com limites."""

from __future__ import annotations

from shiro.config.settings import Settings
from shiro.domain.ports import LLMProvider
from shiro.infrastructure.llm.gemini import GeminiProvider
from shiro.infrastructure.llm.guard import CloudLimits, FallbackProvider, GuardedProvider
from shiro.infrastructure.llm.ollama import OllamaProvider
from shiro.infrastructure.persistence.usage import SqliteUsageLedger
from shiro.infrastructure.system.secrets import get_api_key
from shiro.infrastructure.tools.web import GuardedSearch


def build_web_searcher(settings: Settings, ledger: SqliteUsageLedger) -> GuardedSearch | None:
    """Pesquisa na web pelo Gemini, nos mesmos limites do Tier 2 (precisa da chave)."""
    cloud = settings.llm.cloud
    key = get_api_key("gemini") if cloud.enabled else None
    if not key:
        return None
    limits = CloudLimits(
        rpm_limit=cloud.rpm_limit,
        daily_request_limit=cloud.daily_request_limit,
        daily_budget_usd=cloud.daily_budget_usd,
        price_input_per_mtok=cloud.price_input_per_mtok,
        price_output_per_mtok=cloud.price_output_per_mtok,
    )
    gemini = GeminiProvider(api_key=key, model=cloud.model)
    return GuardedSearch(gemini, GuardedProvider(gemini, limits=limits, ledger=ledger))


def build_local_llm(settings: Settings) -> OllamaProvider:
    local = settings.llm.local
    return OllamaProvider(
        host=local.base_url,
        model=local.model,
        num_ctx=local.num_ctx,
        num_gpu=local.num_gpu,
        keep_alive=local.keep_alive,
    )


def build_cloud_llm(
    settings: Settings, ledger: SqliteUsageLedger
) -> tuple[LLMProvider | None, str]:
    """Provedor do Tier 2 e uma frase de estado para mostrar ao usuário."""
    cloud = settings.llm.cloud
    if not cloud.enabled:
        return None, "nuvem desligada no shiro.toml"
    limits = CloudLimits(
        rpm_limit=cloud.rpm_limit,
        daily_request_limit=cloud.daily_request_limit,
        daily_budget_usd=cloud.daily_budget_usd,
        price_input_per_mtok=cloud.price_input_per_mtok,
        price_output_per_mtok=cloud.price_output_per_mtok,
    )
    chain: list[LLMProvider] = []
    for name in (cloud.provider, *cloud.fallback):
        if name != "gemini":
            continue  # adaptadores Anthropic e OpenAI ainda não existem
        key = get_api_key("gemini")
        if key:
            gemini = GeminiProvider(api_key=key, model=cloud.model)
            chain.append(GuardedProvider(gemini, limits=limits, ledger=ledger))
    if not chain:
        return None, f"nuvem sem chave: rode 'shiro secrets set {cloud.provider}'"
    return FallbackProvider(chain), f"nuvem: {cloud.provider}/{cloud.model}"
