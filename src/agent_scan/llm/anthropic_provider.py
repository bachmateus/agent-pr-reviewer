"""Provider de produção: Claude API pelo SDK oficial `anthropic`."""
from agent_scan.llm.base import BaseProvider, Completion, price_usd


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str, max_tokens: int, prices: dict,
                 effort: str | None = None, client=None):
        super().__init__()
        if client is None:
            import anthropic
            # Lê ANTHROPIC_API_KEY do ambiente. Retry com backoff é do próprio SDK.
            client = anthropic.Anthropic(max_retries=3)
        self._client = client
        self.model = model
        self._max_tokens = max_tokens
        self._prices = prices
        self._effort = effort

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> Completion:
        kwargs = {"model": self.model, "max_tokens": self._max_tokens,
                  "system": system,
                  "messages": [{"role": "user", "content": user}]}
        # Sem `thinking`: no Opus 5.5 ele é sempre ligado e a profundidade
        # se controla só pelo effort.
        output_config = {}
        if self._effort:
            output_config["effort"] = self._effort
        if json_schema:
            # Saída estruturada: a API garante JSON válido nesse schema.
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        if output_config:
            kwargs["output_config"] = output_config
        # Streaming evita timeout de request com max_tokens alto.
        with self._client.messages.stream(**kwargs) as stream:
            msg = stream.get_final_message()

        text = "".join(b.text for b in msg.content if b.type == "text")
        u = msg.usage
        cache_read = u.cache_read_input_tokens or 0
        cache_write = u.cache_creation_input_tokens or 0
        uncached = u.input_tokens or 0
        output = u.output_tokens or 0
        cost = price_usd(self._prices, self.model, uncached, output,
                         cache_read=cache_read, cache_write=cache_write)
        return self._record(Completion(
            text=text, input_tokens=uncached + cache_read + cache_write,
            output_tokens=output, cost_usd=cost, stop_reason=msg.stop_reason))
