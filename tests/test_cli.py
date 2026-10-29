"""Testes dos comandos locais (doctor, ask, review-diff) com o provider fake."""
from pathlib import Path

from agent_scan.cli import main
from agent_scan.reviewer import commentable_lines


def test_review_diff_fixture_com_fake(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert main(["review-diff", "examples/calc.py"]) == 0
    out = capsys.readouterr().out
    assert "(fake)" in out and "custo $0.0000" in out


def test_review_diff_sem_diff(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    f = tmp_path / "x.py"
    f.write_text("x = 1\n")
    assert main(["review-diff", str(f)]) == 2
    assert "diff não encontrado" in capsys.readouterr().out


def test_review_diff_imprime_comentario(monkeypatch, capsys):
    # Comentário numa linha do diff aparece como path:line [severity] body.
    from agent_scan import cli
    from agent_scan.llm.fake import FakeProvider
    raw = ('{"summary":"s","comments":[{"path":"examples/calc.py","line":4,'
           '"severity":"error","body":"divisão por zero"}]}')
    monkeypatch.setattr(cli, "build_provider", lambda cfg: FakeProvider(raw))
    assert main(["review-diff", "examples/calc.py"]) == 0
    assert "examples/calc.py:4 [error] divisão por zero" in capsys.readouterr().out


def test_ask_com_fake(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert main(["ask", "oi?"]) == 0
    assert "tokens: entrada 0 · saída 0" in capsys.readouterr().out


def test_doctor_provider_invalido(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    assert main(["doctor"]) == 1
    assert "[falta]" in capsys.readouterr().out


def test_doctor_fake_sem_github_so_avisa(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    for k in ("GH_APP_ID", "GH_APP_INSTALLATION_ID", "GH_APP_PRIVATE_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "[aviso]" in out and "[falta]" not in out


def test_fixture_diff_tem_linhas_comentaveis():
    patch = Path("examples/calc.py.diff").read_text()
    assert 4 in commentable_lines(patch)  # diff válido e numerado
