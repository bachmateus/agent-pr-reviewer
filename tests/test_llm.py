"""Testes dos providers de LLM — sem rede e sem chamar o `claude` real."""
import json

import pytest

from agent_scan.llm.base import price_usd
from agent_scan.llm.fake import FakeProvider

PRICES = {"claude-opus-5-5": {"input": 4.00, "output": 20.00}}


def test_price_usd_input_output_e_cache():
    # 1M in = $4; 1M out = $20; 1M cache read = $0.40; 1M cache write = $5
    assert price_usd(PRICES, "claude-opus-5-5", 1_000_000, 1_000_000,
                     cache_read=1_000_000, cache_write=1_000_000) == pytest.approx(29.40)


def test_fake_provider_acumula_e_repete_ultima():
    p = FakeProvider(["a", "b"])
    assert [p.complete("s", "u").text for _ in range(3)] == ["a", "b", "b"]
    assert p.calls == 3 and p.cost_usd == 0.0
    assert p.prompts[0] == ("s", "u")


def test_fake_provider_default_e_json_valido():
    assert json.loads(FakeProvider().complete("s", "u").text)["comments"] == []
