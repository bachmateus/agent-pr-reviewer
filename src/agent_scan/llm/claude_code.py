"""Provider local: chama o Claude Code CLI (`claude -p`) já logado na máquina.
Serve para testar o fluxo sem API key. Logado por API key, o CLI cobra como a API."""
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Callable

from agent_scan.llm.base import BaseProvider, Completion


@dataclass
class RunResult:
    code: int
    stdout: str
    stderr: str


# (args, stdin, env, timeout_s) -> RunResult. Injetável para testar sem o CLI.
Runner = Callable[[list[str], str, dict[str, str], float], RunResult]


def build_args(model: str, system: str) -> list[str]:
    """Flags que isolam o CLI: sem ferramentas, sem settings/MCP do usuário,
    sem slash commands e sem gravar sessão. Só texto entra, só texto sai."""
    return ["claude", "-p", "--output-format", "json", "--model", model,
            "--system-prompt", system, "--tools", "", "--setting-sources", "",
            "--strict-mcp-config", "--disable-slash-commands",
            "--no-session-persistence"]


def _subprocess_runner(args: list[str], stdin: str, env: dict[str, str],
                       timeout_s: float) -> RunResult:
    try:
        p = subprocess.run(args, input=stdin, env=env, capture_output=True,
                           text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude-code: timeout após {timeout_s:.0f}s")
    return RunResult(p.returncode, p.stdout, p.stderr)


class ClaudeCodeProvider(BaseProvider):
    def __init__(self, model: str, timeout_s: float = 300.0,
                 runner: Runner | None = None):
        super().__init__()
        self.model = model
        self._timeout_s = timeout_s
        self._run = runner or _subprocess_runner

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> Completion:
        # json_schema é ignorado: o CLI não garante formato. Vale o parse tolerante.
        # Thinking desligado: no teste local, latência importa mais.
        env = {**os.environ, "MAX_THINKING_TOKENS": "0"}
        # O prompt vai por stdin: arquivo inteiro + diff estouraria o limite de argv.
        r = self._run(build_args(self.model, system), user, env, self._timeout_s)
        # Toda falha do CLI vira RuntimeError. Nunca ValueError: o reviewer
        # trata ValueError como "resposta sem JSON" e devolveria review vazio.
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError:
            out = None
        if not isinstance(out, dict):
            out = None
        if r.code != 0:
            # Com --output-format json o erro (ex.: não logado) vem no stdout.
            msg = (out or {}).get("result") or r.stderr.strip() or r.stdout[:500]
            raise RuntimeError(f"claude-code: exit {r.code}: {msg}")
        if out is None:
            raise RuntimeError(f"claude-code: saída não-JSON: {r.stdout[:200]}")
        if out.get("is_error"):
            raise RuntimeError(f"claude-code: {out.get('result', 'erro sem mensagem')}")
        usage = out.get("usage") or {}
        input_tokens = (usage.get("input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0))
        return self._record(Completion(
            text=out.get("result", ""),
            input_tokens=input_tokens,
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=out.get("total_cost_usd", 0.0),
            stop_reason=out.get("stop_reason")))
