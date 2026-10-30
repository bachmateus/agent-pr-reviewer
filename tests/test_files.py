"""Testes do filtro de arquivos revisáveis."""
from agent_scan.files import reviewable


def test_reviewable_filtros():
    assert reviewable("src/app.py", "modified") is True
    assert reviewable("README.md", "modified") is False
    assert reviewable("docs/guia.txt", "modified") is False
    assert reviewable("package-lock.json", "modified") is False
    assert reviewable("src/app.py", "removed") is False
