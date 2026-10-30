"""Webhook de teste: monta um evento como o GitHub mandaria, assina com HMAC
e envia para o /webhook. Testa o serviço local sem abrir PR de verdade."""
import hashlib
import hmac
import json
import urllib.error
import urllib.request


def sign(body: bytes, secret: str) -> str:
    """Mesmo formato do header X-Hub-Signature-256 do GitHub."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _repo(org: str, repo: str) -> dict:
    return {"name": repo, "owner": {"login": org}}


def pr_payload(org: str, repo: str, number: int, action: str = "opened",
               head_sha: str | None = None) -> dict:
    # Sem sha (padrão), o planner busca o head real do PR no GitHub.
    return {"action": action, "repository": _repo(org, repo),
            "pull_request": {"number": number, "draft": False,
                             "user": {"type": "User"},
                             "head": {"sha": head_sha}}}


def comment_payload(org: str, repo: str, number: int, body: str = "/review",
                    author_association: str = "OWNER") -> dict:
    return {"action": "created", "repository": _repo(org, repo),
            "issue": {"number": number, "pull_request": {"url": "..."}},
            "comment": {"body": body, "author_association": author_association}}


def send(url: str, event: str, payload: dict, secret: str) -> int:
    """POST assinado. Devolve o status HTTP (204 = aceito, 401 = assinatura ruim)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-Hub-Signature-256": sign(body, secret),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
