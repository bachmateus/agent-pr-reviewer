"""Testes dos comandos locais (doctor, ask, review-diff) com o provider fake."""
from pathlib import Path

import pytest

from agent_scan.cli import main
from agent_scan.reviewer import commentable_lines


@pytest.fixture(autouse=True)
def _sem_dotenv(monkeypatch):
    # O .env do aluno não pode vazar para os testes (load_dotenv grava em os.environ).
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)


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


def _fake_github(monkeypatch):
    from agent_scan import cli
    from agent_scan import pr as pr_api
    monkeypatch.setattr(cli, "_mint_token", lambda: "t")
    monkeypatch.setattr(pr_api, "list_open_prs",
                        lambda org, repo, token: [{"number": 3, "title": "Ajusta X", "author": "ana"}])
    monkeypatch.setattr(pr_api, "get_pr_files", lambda org, repo, n, token: [
        {"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+x\n", "status": "modified"},
        {"filename": "README.md", "patch": "@@ -1 +1 @@\n+y\n", "status": "modified"}])


def test_list_prs(monkeypatch, capsys):
    _fake_github(monkeypatch)
    assert main(["list-prs", "org/repo"]) == 0
    assert "#3 Ajusta X (ana)" in capsys.readouterr().out


def test_files_marca_revisaveis(monkeypatch, capsys):
    _fake_github(monkeypatch)
    assert main(["files", "org/repo#3"]) == 0
    out = capsys.readouterr().out
    assert "[revisa] src/app.py" in out and "[pula]   README.md" in out


def test_files_alvo_invalido(capsys):
    assert main(["files", "org/repo"]) == 2
    assert "ORG/REPO#NUMERO" in capsys.readouterr().out


def test_send_webhook_assina_com_secret_do_env(monkeypatch, capsys):
    from agent_scan import send_webhook
    seen = {}

    def fake_send(url, event, payload, secret):
        seen.update(url=url, event=event, payload=payload, secret=secret)
        return 204

    monkeypatch.setattr(send_webhook, "send", fake_send)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3gr3d0")
    assert main(["send-webhook", "org/repo#7", "--event", "review"]) == 0
    assert seen["event"] == "issue_comment" and seen["secret"] == "s3gr3d0"
    assert seen["url"] == "http://localhost:8080/webhook"
    assert "HTTP 204" in capsys.readouterr().out
