"""Testes do filtro de arquivos revisáveis."""
from agent_scan.files import reviewable


def test_reviewable_filtros():
    p = "@@ -1 +1 @@\n+x\n"
    assert reviewable("src/app.py", "modified", p) is True
    assert reviewable("README.md", "modified", p) is False
    assert reviewable("docs/guia.txt", "modified", p) is False
    assert reviewable("package-lock.json", "modified", p) is False
    assert reviewable("src/app.py", "removed", p) is False


def test_reviewable_sem_patch_pula():
    # Binário ou diff grande demais: o GitHub não manda patch. Sem patch não
    # há linha comentável — chamar o LLM seria custo puro.
    assert reviewable("src/app.py", "modified", "") is False
    assert reviewable("src/app.py", "modified", None) is False
    assert reviewable("src/app.py", "modified", "@@ -1 +1 @@\n+x\n") is True
