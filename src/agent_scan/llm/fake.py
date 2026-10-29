"""Provider falso: respostas fixas, sem rede e sem custo. Para testes e demo."""
from agent_scan.llm.base import BaseProvider, Completion

DEFAULT_RESPONSE = '{"summary":"(fake) sem revisão real","comments":[]}'


class FakeProvider(BaseProvider):
    def __init__(self, responses: list[str] | str | None = None):
        super().__init__()
        if responses is None:
            responses = [DEFAULT_RESPONSE]
        elif isinstance(responses, str):
            responses = [responses]
        self._responses = list(responses)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system: str, user: str,
                 json_schema: dict | None = None) -> Completion:
        self.prompts.append((system, user))
        # Devolve em ordem; esgotou, repete a última.
        i = min(len(self.prompts) - 1, len(self._responses) - 1)
        return self._record(Completion(text=self._responses[i],
                                       stop_reason="end_turn"))
