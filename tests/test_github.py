"""Testes da camada do GitHub com o helper http trocado por um falso."""
import pytest

from agent_scan import pr as pr_api


@pytest.fixture
def fake_http(monkeypatch):
    calls = []
    responses = {}

    def http(method, url, token, payload=None):
        calls.append((method, url, payload))
        for prefix, resp in responses.items():
            if url.startswith(prefix):
                return resp
        return 200, {}

    monkeypatch.setattr(pr_api, "http", http)
    return calls, responses


def test_list_open_prs(fake_http):
    calls, responses = fake_http
    responses[f"{pr_api._API}/repos/org/repo/pulls"] = (
        200, [{"number": 3, "title": "Ajusta X", "user": {"login": "ana"}}])
    assert pr_api.list_open_prs("org", "repo", "t") == [
        {"number": 3, "title": "Ajusta X", "author": "ana"}]
    assert "state=open" in calls[0][1]


def test_list_open_prs_erro_levanta(fake_http):
    _, responses = fake_http
    responses[f"{pr_api._API}/repos/org/repo/pulls"] = (404, {"message": "Not Found"})
    with pytest.raises(RuntimeError, match="404"):
        pr_api.list_open_prs("org", "repo", "t")


def test_get_pr_files_pagina(fake_http):
    _, responses = fake_http
    page1 = [{"filename": f"f{i}.py", "patch": "@@", "status": "modified"} for i in range(100)]
    responses[f"{pr_api._API}/repos/org/repo/pulls/1/files?per_page=100&page=1"] = (200, page1)
    responses[f"{pr_api._API}/repos/org/repo/pulls/1/files?per_page=100&page=2"] = (
        200, [{"filename": "ultimo.py", "status": "added"}])
    files = pr_api.get_pr_files("org", "repo", 1, "t")
    assert len(files) == 101 and files[-1] == {"filename": "ultimo.py", "patch": "", "status": "added"}


def test_post_review_com_fallback_422_posta_resumo_e_comentarios_um_a_um(fake_http):
    from agent_scan.models import ReviewComment
    calls, _ = fake_http
    results = iter([(422, {"message": "Line could not be resolved"}),  # review com tudo
                    (200, {}),                                          # só o resumo
                    (201, {}),                                          # inline 1 ok
                    (422, {"message": "line"})])                        # inline 2 falha
    pr_api.http = lambda method, url, token, payload=None: (calls.append((method, url, payload)) or next(results))
    comments = [ReviewComment("a.py", 1, "info", "ok"), ReviewComment("a.py", 99, "info", "fora")]
    posted = pr_api.post_review_with_fallback("o", "r", 1, "t", "resumo", comments, "abc")
    assert posted == 1
    assert calls[1][2]["comments"] == [] and calls[1][2]["body"] == "resumo"
    assert calls[2][1].endswith("/pulls/1/comments") and calls[2][2]["commit_id"] == "abc"


def test_post_review_com_fallback_sem_erro_posta_tudo_de_uma_vez(fake_http):
    from agent_scan.models import ReviewComment
    calls, _ = fake_http
    posted = pr_api.post_review_with_fallback(
        "o", "r", 1, "t", "resumo", [ReviewComment("a.py", 1, "info", "ok")], "abc")
    assert posted == 1 and len(calls) == 1


def test_post_review_com_fallback_outro_erro_levanta(fake_http):
    _, responses = fake_http
    responses[f"{pr_api._API}/repos/o/r/pulls/1/reviews"] = (403, {"message": "Forbidden"})
    with pytest.raises(RuntimeError, match="403"):
        pr_api.post_review_with_fallback("o", "r", 1, "t", "resumo", [], "abc")


def test_post_review_amarra_ao_commit_revisado(fake_http):
    # Sem commit_id o GitHub marca o review no head ATUAL: com push novo no
    # meio do caminho, o commit novo pareceria revisado e nunca seria.
    calls, _ = fake_http
    pr_api.post_review("o", "r", 1, "t", "resumo", [], commit_id="sha1")
    assert calls[0][2]["commit_id"] == "sha1"
