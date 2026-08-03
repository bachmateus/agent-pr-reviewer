"""Adaptador fino em cima do litellm: retry com backoff e contabilidade de custo."""
import time


class LiteLLMProvider:
    def __init__(self, model: str, max_retries: int = 3,
                 max_tokens: int | None = None):
        import litellm
        self.model = model
        self._completion = litellm.completion
        # Teto de tokens de saída. Modelos com thinking (ex.: Opus) gastam
        # tokens raciocinando ANTES do content; teto baixo trunca
        # (finish_reason=length) com content VAZIO. None = default do litellm.
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        # Contabilidade de ROI: tokens e custo acumulados por execução.
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def complete(self, system: str, user: str) -> str:
        attempt = 0
        while True:
            try:
                kwargs = {"model": self.model, "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]}
                if self._max_tokens is not None:
                    kwargs["max_tokens"] = self._max_tokens
                resp = self._completion(**kwargs)
                break
            except Exception:
                attempt += 1
                if attempt > self._max_retries:
                    raise
                time.sleep(min(2 ** attempt, 30))
        import litellm
        usage = getattr(resp, "usage", None)
        self.calls += 1
        if usage is not None:
            self.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.output_tokens += getattr(usage, "completion_tokens", 0) or 0
        try:  # custo é best-effort: modelo sem tabela de preço não derruba nada
            self.cost_usd += litellm.completion_cost(completion_response=resp) or 0.0
        except Exception:
            pass
        return resp.choices[0].message.content
