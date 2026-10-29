"""Testes dos providers de LLM — sem rede e sem chamar o `claude` real."""
import json
import re
from types import SimpleNamespace

import pytest

from agent_scan.llm import build_provider
from agent_scan.llm.anthropic_provider import AnthropicProvider
from agent_scan.llm.base import price_usd
from agent_scan.llm.claude_code import ClaudeCodeProvider, RunResult, build_args
from agent_scan.llm.fake import FakeProvider
from agent_scan.reviewer import REVIEW_SCHEMA, review_file

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


def test_build_provider_fake_por_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert isinstance(build_provider({"provider": "anthropic"}), FakeProvider)


def test_build_provider_invalido(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    with pytest.raises(ValueError, match=re.escape("anthropic | claude-code | fake")):
        build_provider({})


def test_price_usd_modelo_sem_preco(capsys):
    assert price_usd(PRICES, "modelo-x", 1000, 1000) == 0.0
    assert "modelo-x" in capsys.readouterr().err


def test_review_file_com_fake_filtra_linha():
    raw = ('{"summary":"s","comments":[{"path":"a.py","line":2,"severity":"info","body":"ok"},'
           '{"path":"a.py","line":99,"severity":"info","body":"alucinada"}]}')
    r = review_file("a.py", "@@ -1,1 +1,2 @@\n x\n+y\n", "x\ny\n", FakeProvider(raw))
    assert [c.line for c in r.comments] == [2]


OK = json.dumps({"result": "oi", "is_error": False, "stop_reason": "end_turn",
                 "total_cost_usd": 0.0123,
                 "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
                           "cache_creation_input_tokens": 2, "output_tokens": 7}})


def test_claude_code_prompt_vai_por_stdin_e_flags_isoladas():
    seen = {}

    def runner(args, stdin, env, timeout):
        seen.update(args=args, stdin=stdin, env=env)
        return RunResult(0, OK, "")

    c = ClaudeCodeProvider("claude-haiku-5-5", runner=runner).complete("SYS", "PROMPT GRANDE")
    assert seen["stdin"] == "PROMPT GRANDE" and "PROMPT GRANDE" not in seen["args"]
    assert seen["args"] == build_args("claude-haiku-5-5", "SYS")
    assert seen["env"]["MAX_THINKING_TOKENS"] == "0"
    assert (c.text, c.input_tokens, c.output_tokens, c.cost_usd) == ("oi", 17, 7, 0.0123)


def test_claude_code_build_args_exatos():
    assert build_args("m", "S") == [
        "claude", "-p", "--output-format", "json", "--model", "m",
        "--system-prompt", "S", "--tools", "", "--setting-sources", "",
        "--strict-mcp-config", "--disable-slash-commands",
        "--no-session-persistence"]


def test_claude_code_is_error_com_exit_zero_levanta():
    bad = json.dumps({"result": "Not logged in", "is_error": True})
    p = ClaudeCodeProvider("m", runner=lambda *a: RunResult(0, bad, ""))
    with pytest.raises(RuntimeError, match="Not logged in"):
        p.complete("s", "u")


def test_claude_code_exit_nao_zero_levanta_com_stderr():
    p = ClaudeCodeProvider("m", runner=lambda *a: RunResult(1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        p.complete("s", "u")


class _Stream:
    def __init__(self, msg):
        self._msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._msg


class FakeClient:
    """Imita client.messages.stream(**kw) do SDK e guarda os kwargs enviados."""
    def __init__(self, msg):
        self.last_kwargs = None
        self.messages = self
        self._msg = msg

    def stream(self, **kw):
        self.last_kwargs = kw
        return _Stream(self._msg)


def _msg(blocks, stop="end_turn"):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                            cache_read_input_tokens=None, cache_creation_input_tokens=0)
    return SimpleNamespace(content=blocks, usage=usage, stop_reason=stop)


def test_anthropic_monta_request_e_custo():
    client = FakeClient(_msg([SimpleNamespace(type="thinking"),
                              SimpleNamespace(type="text", text='{"a":1}')]))
    p = AnthropicProvider("claude-opus-5-5", 20000, PRICES, effort="low", client=client)
    c = p.complete("SYS", "U", json_schema={"type": "object"})
    kw = client.last_kwargs
    assert kw["system"] == "SYS" and "thinking" not in kw
    assert kw["messages"] == [{"role": "user", "content": "U"}]
    assert kw["output_config"] == {"effort": "low",
                                   "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert c.text == '{"a":1}' and c.cost_usd == pytest.approx(0.014)  # (1000×4 + 500×20) / 1e6
    assert p.calls == 1 and p.input_tokens == 1000


def test_anthropic_sem_schema_nem_effort_nao_envia_output_config():
    client = FakeClient(_msg([SimpleNamespace(type="text", text="x")]))
    AnthropicProvider("claude-opus-5-5", 100, PRICES, client=client).complete("s", "u")
    assert "output_config" not in client.last_kwargs


def test_anthropic_sem_bloco_de_texto_devolve_vazio_e_stop_reason():
    client = FakeClient(_msg([SimpleNamespace(type="thinking")], stop="max_tokens"))
    c = AnthropicProvider("claude-opus-5-5", 100, PRICES, client=client).complete("s", "u")
    assert (c.text, c.stop_reason) == ("", "max_tokens")


def test_review_schema_fecha_os_dois_niveis():
    item = REVIEW_SCHEMA["properties"]["comments"]["items"]
    assert REVIEW_SCHEMA["additionalProperties"] is False and item["additionalProperties"] is False
    assert set(item["required"]) == {"path", "line", "severity", "body"}
    assert item["properties"]["severity"]["enum"] == ["info", "warning", "error"]


def test_review_file_manda_schema():
    class Spy(FakeProvider):
        def complete(self, system, user, json_schema=None):
            self.schema = json_schema
            return super().complete(system, user)

    s = Spy()
    review_file("a.py", "@@ -1 +1 @@\n+x\n", "x\n", s)
    assert s.schema is REVIEW_SCHEMA


def test_claude_code_exit_nao_zero_usa_result_do_json():
    # Não logado: CLI sai com 1 e manda o erro no JSON do stdout, stderr vazio.
    bad = json.dumps({"is_error": True, "result": "Invalid API key · Please run /login"})
    p = ClaudeCodeProvider("m", runner=lambda *a: RunResult(1, bad, ""))
    with pytest.raises(RuntimeError, match="Please run /login"):
        p.complete("s", "u")


def test_claude_code_stdout_nao_json_levanta_runtime_error():
    # Não pode virar ValueError: o reviewer engoliria como review vazio.
    p = ClaudeCodeProvider("m", runner=lambda *a: RunResult(0, "Error: not json", ""))
    with pytest.raises(RuntimeError, match="não-JSON"):
        p.complete("s", "u")
