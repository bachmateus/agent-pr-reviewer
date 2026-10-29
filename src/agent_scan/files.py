"""Filtro de arquivos revisáveis — usado pelo comando local e pelo planner."""

_SKIP_EXT = (".md",)
_SKIP_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml",
               "poetry.lock", "go.sum", "gemfile.lock"}


def reviewable(path: str, status: str) -> bool:
    """Cada arquivo é uma chamada paga de LLM — pula o que não gera valor."""
    if status == "removed":
        return False
    p = path.lower()
    if p.endswith(_SKIP_EXT):
        return False
    if p.startswith("docs/"):
        return False
    if p.rsplit("/", 1)[-1] in _SKIP_NAMES:
        return False
    return True
