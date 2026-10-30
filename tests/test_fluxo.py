"""Testes do fluxo com GitHub, Pub/Sub e Cloud Tasks falsos — sem rede."""
import hashlib
import hmac
import json
from types import SimpleNamespace

from agent_scan import pr as pr_api
from agent_scan.cli import main
from agent_scan.llm.fake import FakeProvider
from agent_scan.models import ReviewComment

PATCH = "@@ -1,2 +1,3 @@\n a = 1\n+b = a / 0\n c = 2\n"
CONTENT = "a = 1\nb = a / 0\nc = 2\n"
RAW = ('{"summary":"resumo","comments":['
       '{"path":"src/a.py","line":2,"severity":"error","body":"divisão por zero"},'
       '{"path":"src/a.py","line":99,"severity":"info","body":"linha alucinada"}]}')


def test_render_comment_poe_badge_de_severidade():
    assert pr_api.render_comment(ReviewComment("a.py", 1, "error", "x")).startswith("🛑 **Erro**")
    assert pr_api.render_comment(ReviewComment("a.py", 1, "outra", "x")).startswith("ℹ️")


def _github(monkeypatch, posted):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr("agent_scan.cli._mint_token", lambda: "t")
    monkeypatch.setattr(pr_api, "get_pr_head", lambda *a: "abc")
    monkeypatch.setattr(pr_api, "get_pr_files", lambda *a: [
        {"filename": "src/a.py", "patch": PATCH, "status": "modified"},
        {"filename": "README.md", "patch": "@@ -1 +1 @@\n+x\n", "status": "modified"}])
    monkeypatch.setattr(pr_api, "get_file_content", lambda *a: CONTENT)
    monkeypatch.setattr(pr_api, "post_review",
                        lambda org, repo, number, token, body, comments:
                        posted.append((body, comments)))


def test_review_posta_resumo_e_so_comentarios_do_diff(monkeypatch, capsys):
    from agent_scan import cli
    posted = []
    _github(monkeypatch, posted)
    monkeypatch.setattr(cli, "build_provider", lambda cfg: FakeProvider(RAW))
    assert main(["review", "org/repo#3"]) == 0
    body, comments = posted[0]
    assert body == "resumo"
    assert [(c.path, c.line) for c in comments] == [("src/a.py", 2)]   # a 99 caiu no filtro
    assert "2 arquivos, 1 revisáveis" in capsys.readouterr().out


def test_handle_request_webhook_assinado_publica_job():
    from agent_scan.webhook import handle_request
    published = []
    publisher = SimpleNamespace(publish=lambda topic, data: (
        published.append(data) or SimpleNamespace(result=lambda: "id")))
    cfg = SimpleNamespace(secret="s3gr3d0", topic_path="t", publisher=publisher)
    payload = {"action": "opened", "repository": {"name": "repo", "owner": {"login": "org"}},
               "pull_request": {"number": 7, "draft": False, "user": {"type": "User"},
                                "head": {"sha": "abc"}}}
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"s3gr3d0", body, hashlib.sha256).hexdigest()
    headers = {"X-Hub-Signature-256": sig, "X-GitHub-Event": "pull_request"}
    assert handle_request(cfg, "/webhook", headers, body) == (204, b"")
    assert json.loads(published[0])["number"] == 7
    bad = {**headers, "X-Hub-Signature-256": "sha256=forjada"}
    assert handle_request(cfg, "/webhook", bad, body)[0] == 401
    assert len(published) == 1


class FakeTasks:
    def __init__(self):
        self.created = []

    def create_task(self, parent, task):
        self.created.append((parent, task))


def _job():
    return {"org": "org", "repo": "repo", "number": 3, "head_sha": "abc"}


def test_plan_review_uma_task_por_arquivo_e_posta_resumo(monkeypatch):
    from agent_scan import webhook
    posted = []
    _github(monkeypatch, posted)
    monkeypatch.setattr(pr_api, "has_reviewed_sha", lambda *a: False)
    tasks = FakeTasks()
    n = webhook.plan_review(_job(), FakeProvider(RAW), "t", tasks, "q",
                            "https://svc/chunk", "sa@x", "https://svc", "bot[bot]")
    assert n == 1 and len(tasks.created) == 1        # README.md fica de fora
    parent, task = tasks.created[0]
    chunk = json.loads(task["http_request"]["body"])
    assert parent == "q" and chunk["path"] == "src/a.py" and chunk["commit_id"] == "abc"
    assert task["http_request"]["oidc_token"] == {"service_account_email": "sa@x",
                                                  "audience": "https://svc"}
    assert posted == [("resumo", [])]                # resumo sem inline: inline é do worker


def test_plan_review_commit_ja_revisado_nao_faz_nada(monkeypatch):
    from agent_scan import webhook
    posted = []
    _github(monkeypatch, posted)
    monkeypatch.setattr(pr_api, "has_reviewed_sha", lambda *a: True)
    tasks = FakeTasks()
    assert webhook.plan_review(_job(), FakeProvider(RAW), "t", tasks, "q",
                               "https://svc/chunk", "sa@x", "https://svc", "bot[bot]") == 0
    assert tasks.created == [] and posted == []


def _chunk():
    return {"org": "org", "repo": "repo", "number": 3, "commit_id": "abc",
            "head_sha": "abc", "path": "src/a.py", "status": "modified", "patch": PATCH}


def test_process_chunk_posta_inline_so_linha_do_diff(monkeypatch):
    from agent_scan import webhook
    inline = []
    monkeypatch.setattr(pr_api, "has_reviewed_path", lambda *a: False)
    monkeypatch.setattr(pr_api, "get_file_content", lambda *a: CONTENT)
    monkeypatch.setattr(pr_api, "post_inline_comment",
                        lambda org, repo, number, token, commit_id, path, line, body:
                        inline.append((path, line, body)))
    assert webhook.process_chunk(_chunk(), FakeProvider(RAW), "t", "bot[bot]") == "reviewed"
    assert [(p, ln) for p, ln, _ in inline] == [("src/a.py", 2)]
    assert inline[0][2].startswith("🛑 **Erro**")


def test_process_chunk_ja_comentado_pula(monkeypatch):
    from agent_scan import webhook
    monkeypatch.setattr(pr_api, "has_reviewed_path", lambda *a: True)
    provider = FakeProvider(RAW)
    assert webhook.process_chunk(_chunk(), provider, "t", "bot[bot]") == "skipped_idempotent"
    assert provider.calls == 0
