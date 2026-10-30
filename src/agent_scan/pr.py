"""Camada de API do GitHub: helper http único, arquivos do PR, reviews e
comentários inline. urllib puro — sem client de terceiro."""
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from agent_scan.models import ReviewComment

_API = "https://api.github.com"


def http(method: str, url: str, token: str,
         payload: dict | None = None) -> tuple[int, dict | list]:
    """Helper único de HTTP para o GitHub. Devolve sempre (status, body_json)."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, body = resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read().decode("utf-8")
    try:
        return status, (json.loads(body) if body else {})
    except json.JSONDecodeError:
        return status, {}


def list_open_prs(org: str, repo: str, token: str) -> list[dict]:
    """PRs abertos (1ª página). Serve de checkpoint: o token funciona?"""
    status, body = http("GET",
        f"{_API}/repos/{org}/{repo}/pulls?state=open&per_page=30", token)
    if status >= 400:
        raise RuntimeError(f"GitHub: listar PRs falhou (HTTP {status}): {body}")
    return [{"number": p.get("number"), "title": p.get("title", ""),
             "author": (p.get("user") or {}).get("login", "")} for p in body]


def get_pr_head(org: str, repo: str, number: int, token: str) -> str:
    status, body = http("GET", f"{_API}/repos/{org}/{repo}/pulls/{number}", token)
    if status >= 400:
        raise RuntimeError(f"GitHub: get PR falhou (HTTP {status}): {body}")
    return (body.get("head") or {}).get("sha")


def get_pr_files(org: str, repo: str, number: int, token: str) -> list[dict]:
    files, page = [], 1
    while True:
        status, body = http("GET",
            f"{_API}/repos/{org}/{repo}/pulls/{number}/files"
            f"?per_page=100&page={page}", token)
        if status >= 400:
            raise RuntimeError(f"GitHub: listar files falhou (HTTP {status}): {body}")
        for item in body:
            files.append({"filename": item.get("filename", ""),
                          "patch": item.get("patch") or "",
                          "status": item.get("status", "")})
        if len(body) < 100:
            return files
        page += 1


def get_file_content(org: str, repo: str, path: str, ref: str, token: str,
                     max_bytes: int = 100_000) -> str | None:
    """Conteúdo completo do arquivo no head do PR (contexto > diff).
    Best-effort: None para binário, arquivo grande ou erro de API —
    o review daquele arquivo segue só com o patch."""
    q = urllib.parse.quote(path)
    status, body = http("GET", f"{_API}/repos/{org}/{repo}/contents/{q}?ref={ref}", token)
    if status >= 400 or not isinstance(body, dict):
        return None
    if body.get("encoding") != "base64" or (body.get("size") or 0) > max_bytes:
        return None
    try:
        return base64.b64decode(body.get("content", "")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


# Badge de severidade no topo de cada comentário (markdown).
_SEVERITY_BADGE = {
    "error": "🛑 **Erro**",
    "warning": "⚠️ **Atenção**",
    "info": "ℹ️ **Sugestão**",
}


def render_comment(c: ReviewComment) -> str:
    badge = _SEVERITY_BADGE.get(c.severity, _SEVERITY_BADGE["info"])
    return f"{badge}\n\n{c.body}"


def post_review(org: str, repo: str, number: int, token: str, body: str,
                comments: list[ReviewComment]) -> None:
    """Review formal com resumo + comentários. event=COMMENT sempre:
    o agente informa, o humano decide o merge."""
    payload = {
        "event": "COMMENT",
        "body": body,
        "comments": [{"path": c.path, "line": c.line,
                      "side": "RIGHT", "body": render_comment(c)}
                     for c in comments],
    }
    status, resp = http("POST",
        f"{_API}/repos/{org}/{repo}/pulls/{number}/reviews", token, payload)
    if status >= 400:
        raise RuntimeError(f"GitHub: postar review falhou (HTTP {status}): {resp}")


def post_inline_comment(org: str, repo: str, number: int, token: str,
                        commit_id: str, path: str, line: int, body: str) -> None:
    """Comentário de review em UMA linha (não cria review novo por comentário).
    Best-effort: um 422 residual (linha fora do diff) é logado, não derruba."""
    payload = {"commit_id": commit_id, "path": path, "line": line,
               "side": "RIGHT", "body": body}
    status, resp = http("POST",
        f"{_API}/repos/{org}/{repo}/pulls/{number}/comments", token, payload)
    if status >= 400:
        print(f"aviso: comentário inline falhou (HTTP {status}) em {path}:{line}",
              file=sys.stderr, flush=True)


def has_reviewed_sha(org: str, repo: str, number: int, token: str,
                     bot_login: str, head_sha: str) -> bool:
    """Guarda de idempotência do planner: já existe review do bot neste commit?
    Paginada — em PR com muitos reviews, olhar só a 1ª página duplica review."""
    page = 1
    while True:
        status, body = http("GET",
            f"{_API}/repos/{org}/{repo}/pulls/{number}/reviews"
            f"?per_page=100&page={page}", token)
        if status >= 400:
            raise RuntimeError(f"GitHub: listar reviews falhou (HTTP {status}): {body}")
        for item in body:
            user = item.get("user") or {}
            if user.get("login") == bot_login and item.get("commit_id") == head_sha:
                return True
        if len(body) < 100:
            return False
        page += 1


def has_reviewed_path(org: str, repo: str, number: int, token: str,
                      bot_login: str, commit_id: str, path: str) -> bool:
    """Guarda de idempotência do worker: já comentei este (commit, arquivo)?"""
    page = 1
    while True:
        status, body = http("GET",
            f"{_API}/repos/{org}/{repo}/pulls/{number}/comments"
            f"?per_page=100&page={page}", token)
        if status >= 400:
            raise RuntimeError(f"GitHub: listar comentários falhou (HTTP {status}): {body}")
        for item in body:
            user = item.get("user") or {}
            if (user.get("login") == bot_login
                    and item.get("commit_id") == commit_id
                    and item.get("path") == path):
                return True
        if len(body) < 100:
            return False
        page += 1
