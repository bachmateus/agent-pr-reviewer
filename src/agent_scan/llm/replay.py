"""Replay em cache: a mesma pergunta ao mesmo modelo responde do disco.
Rodar o eval de novo sem mudar o prompt não custa nada."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from agent_scan.llm.base import BaseProvider, Completion

# Resposta cortada não vai para o cache: o conserto (subir max_tokens, mudar
# o prompt) tem que chegar a chamar o modelo de novo.
_NO_CACHE_STOPS = {"max_tokens", "refusal"}


class ReplayProvider(BaseProvider):
    def __init__(self, inner: BaseProvider, cache_dir: Path, key_prefix: str):
        super().__init__()
        self._inner = inner
        self._dir = Path(cache_dir)
        # key_prefix = provider + modelo + parâmetros: mudar qualquer um invalida o cache.
        self._prefix = key_prefix
        self.hits = 0
        self.misses = 0

    def _key(self, system: str, user: str, json_schema: dict | None) -> str:
        raw = json.dumps({"k": self._prefix, "s": system, "u": user,
                          "j": json_schema}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> Completion:
        path = self._dir / f"{self._key(system, user, json_schema)}.json"
        if path.exists():
            self.hits += 1
            data = json.loads(path.read_text())
            # Do cache: tokens são os originais, custo desta execução é zero.
            return self._record(Completion(**{**data, "cost_usd": 0.0}))
        self.misses += 1
        c = self._inner.complete(system, user, json_schema)
        if c.stop_reason not in _NO_CACHE_STOPS:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(c), ensure_ascii=False))
        return self._record(c)
