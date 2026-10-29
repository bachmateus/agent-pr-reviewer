"""Providers de LLM. Trocar de provider = mudar `provider` no config.yaml
ou a variável de ambiente LLM_PROVIDER."""
import os

from agent_scan.llm.base import BaseProvider

PROVIDERS = ("anthropic", "claude-code", "fake")


def build_provider(cfg: dict) -> BaseProvider:
    name = os.environ.get("LLM_PROVIDER") or cfg.get("provider", "anthropic")
    # Imports dentro dos ramos: o fake não precisa do SDK instalado.
    if name == "fake":
        from agent_scan.llm.fake import FakeProvider
        return FakeProvider()
    if name == "anthropic":
        from agent_scan.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=cfg["review_model"],
                                 max_tokens=cfg.get("review_max_tokens", 20000),
                                 prices=cfg.get("prices_usd_per_mtok", {}),
                                 effort=cfg.get("review_effort"))
    if name == "claude-code":
        from agent_scan.llm.claude_code import ClaudeCodeProvider
        return ClaudeCodeProvider(model=cfg["review_model"])
    raise ValueError(f"provider inválido: {name} (use {' | '.join(PROVIDERS)})")
