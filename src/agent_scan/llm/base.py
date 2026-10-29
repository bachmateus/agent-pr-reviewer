"""Contrato comum dos providers de LLM: resposta + contabilidade de custo."""
import sys
from dataclasses import dataclass

# Multiplicadores do preço de input para tokens de cache (prompt caching).
CACHE_READ_MULT = 0.1
CACHE_WRITE_MULT = 1.25


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # Por que o modelo parou (end_turn, max_tokens, refusal...). None = provider não informa.
    stop_reason: str | None = None


def price_usd(prices: dict, model: str, input_tokens: int, output_tokens: int,
              cache_read: int = 0, cache_write: int = 0) -> float:
    """Custo em USD a partir da tabela {modelo: {input, output}} em USD/MTok.
    Modelo fora da tabela custa 0 com aviso: custo nunca derruba o review."""
    p = prices.get(model)
    if not p:
        print(f"aviso: modelo {model} sem preço na tabela; custo = 0",
              file=sys.stderr)
        return 0.0
    inp, out = p["input"], p["output"]
    return (input_tokens * inp
            + cache_read * inp * CACHE_READ_MULT
            + cache_write * inp * CACHE_WRITE_MULT
            + output_tokens * out) / 1_000_000


class BaseProvider:
    """Todo provider implementa complete() e acumula tokens e custo da execução."""

    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> Completion:
        raise NotImplementedError

    def _record(self, c: Completion) -> Completion:
        self.calls += 1
        self.input_tokens += c.input_tokens
        self.output_tokens += c.output_tokens
        self.cost_usd += c.cost_usd
        return c
