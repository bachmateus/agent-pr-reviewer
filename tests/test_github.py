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
