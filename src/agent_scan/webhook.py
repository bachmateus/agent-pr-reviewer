"""Serviço HTTP do reviewer (stdlib http.server, sem framework).

Rotas:
  /webhook  — GitHub entrega o evento; valida HMAC e publica no Pub/Sub
  /process  — Pub/Sub (push + OIDC) acorda o PLANNER: 1 Cloud Task por arquivo + resumo
  /chunk    — Cloud Tasks (OIDC) acorda o WORKER: revisa 1 arquivo, posta inline
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_scan import pr as pr_api
from agent_scan import reviewer as reviewer_mod
from agent_scan.files import reviewable
from agent_scan.github_app import mint_installation_token


# ---------------------------------------------------------------- webhook ---

def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 do body com o secret compartilhado. compare_digest =
    comparação em tempo constante (evita timing attack)."""
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# Quem pode pedir /review: só quem tem acesso ao repo. Em repo público qualquer
# conta comenta, e cada /review é chamada paga de LLM.
_REVIEW_ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}


def select_event(event: str, payload: dict, command: str = "/review") -> dict | None:
    """Filtra eventos do GitHub e devolve o job de review, ou None.

    Reviso quando o PR abre; ignoro drafts e PRs abertos por bots (loop de
    custo). Comentário `/review` força re-review (fura a idempotência)."""
    repo = payload.get("repository") or {}
    org = (repo.get("owner") or {}).get("login")
    name = repo.get("name")
    if not org or not name:
        return None

    if event == "pull_request":
        if payload.get("action") != "opened":
            return None
        prq = payload.get("pull_request") or {}
        if prq.get("draft"):
            return None
        if (prq.get("user") or {}).get("type") == "Bot":
            return None
        return {"org": org, "repo": name, "number": prq.get("number"),
                "head_sha": (prq.get("head") or {}).get("sha")}

    if event == "issue_comment":
        if payload.get("action") != "created":
            return None
        issue = payload.get("issue") or {}
        if not issue.get("pull_request"):
            return None
        comment = payload.get("comment") or {}
        body = (comment.get("body") or "").strip()
        if not body.lower().startswith(command):
            return None
        if comment.get("author_association") not in _REVIEW_ALLOWED:
            return None
        return {"org": org, "repo": name, "number": issue.get("number"),
                "head_sha": None, "force": True}

    return None


class StdoutPublisher:
    """Publisher local (PUBSUB_TOPIC=stdout): imprime o job em vez de mandar
    pro Pub/Sub. Testa o /webhook sem GCP."""

    class _Done:
        def result(self):
            return "local"

    def publish(self, topic_path: str, data: bytes):
        print(f"job publicado: {data.decode('utf-8')}", flush=True)
        return self._Done()


def publish_job(publisher, topic_path: str, job: dict) -> None:
    future = publisher.publish(topic_path, json.dumps(job).encode("utf-8"))
    future.result()


def decode_push(envelope: dict) -> dict:
    """O push do Pub/Sub não entrega seu JSON direto: vem embrulhado em
    {"message": {"data": "<base64>"}}. Aqui desembrulha e decodifica."""
    data = (envelope.get("message") or {}).get("data", "")
    return json.loads(base64.b64decode(data).decode("utf-8"))


# ---------------------------------------------------------------- planner ---

# Cloud Tasks limita o body da task em ~1MB. Patch acima disso é TRUNCADO
# pelo prefixo, nunca zerado: patch vazio faria commentable_lines descartar
# todo comentário do arquivo.
_TASK_BODY_LIMIT = 900_000


def enqueue_chunk(tasks_client, queue_path: str, chunk_url: str,
                  oidc_sa: str, audience: str, chunk: dict) -> None:
    body = json.dumps(chunk).encode("utf-8")
    if len(body) > _TASK_BODY_LIMIT:
        overhead = len(json.dumps({**chunk, "patch": ""}).encode("utf-8"))
        patch = chunk.get("patch", "")[:max(0, _TASK_BODY_LIMIT - overhead - 256)]
        chunk = {**chunk, "patch": patch}
        body = json.dumps(chunk).encode("utf-8")
        while len(body) > _TASK_BODY_LIMIT and patch:
            patch = patch[:len(patch) // 2]
            chunk = {**chunk, "patch": patch}
            body = json.dumps(chunk).encode("utf-8")
    task = {
        "http_request": {
            "http_method": "POST",
            "url": chunk_url,
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": oidc_sa,
                "audience": audience,
            },
        }
    }
    tasks_client.create_task(parent=queue_path, task=task)


def plan_review(job: dict, provider, token: str, tasks_client, queue_path: str,
                chunk_url: str, oidc_sa: str, audience: str,
                bot_login: str) -> int:
    """PLANNER: fatia o PR em 1 chunk por arquivo revisável e posta o resumo.
    Idempotente por head_sha, salvo force (`/review` explícito)."""
    org, repo, number = job["org"], job["repo"], job["number"]
    head_sha = job.get("head_sha") or pr_api.get_pr_head(org, repo, number, token)
    force = bool(job.get("force"))
    if not force and pr_api.has_reviewed_sha(
            org, repo, number, token, bot_login, head_sha):
        return 0   # pub/sub re-entregou; já revisei esse commit
    files = pr_api.get_pr_files(org, repo, number, token)
    revs = [f for f in files if reviewable(f["filename"], f.get("status", ""))]
    for f in revs:
        enqueue_chunk(tasks_client, queue_path, chunk_url, oidc_sa, audience, {
            "org": org, "repo": repo, "number": number,
            "head_sha": head_sha, "commit_id": head_sha,
            "path": f["filename"], "status": f.get("status", ""),
            "patch": f.get("patch", ""), "force": force,
        })
    summary = reviewer_mod.summarize_pr(revs, provider) if revs \
        else "Sem arquivos de codigo para revisar neste PR."
    pr_api.post_review(org, repo, number, token,
                       summary or "Revisao automatica.", [])
    return len(revs)


# ----------------------------------------------------------------- worker ---

def process_chunk(chunk: dict, provider, token: str, bot_login: str) -> str:
    """WORKER: revisa UM arquivo e posta os comentários inline.
    Idempotente por (commit_id, path), salvo force."""
    org, repo, number = chunk["org"], chunk["repo"], chunk["number"]
    commit_id, path = chunk["commit_id"], chunk["path"]
    if not chunk.get("force") and pr_api.has_reviewed_path(
            org, repo, number, token, bot_login, commit_id, path):
        return "skipped_idempotent"
    content = None
    if chunk.get("status") != "removed":
        content = pr_api.get_file_content(org, repo, path, chunk["head_sha"], token)
    result = reviewer_mod.review_file(path, chunk.get("patch", ""), content, provider)
    for c in result.comments:
        pr_api.post_inline_comment(org, repo, number, token, commit_id,
                                   c.path, c.line, pr_api.render_comment(c))
    return "reviewed"


# --------------------------------------------------------------- roteador ---

def handle_request(cfg, path: str, headers: dict, body: bytes) -> tuple[int, bytes]:
    """Roteia requisições puras (sem socket) — testável sem servidor."""
    # O load balancer do Google normaliza os headers pra minúsculo ao entregar
    # no container; a busca tem que ser case-insensitive.
    h = {k.lower(): v for k, v in headers.items()}

    if path == "/webhook":
        sig = h.get("x-hub-signature-256", "")
        if not verify_signature(body, sig, cfg.secret):
            return 401, b"bad signature"
        event = h.get("x-github-event", "")
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return 400, b"invalid json"
        job = select_event(event, payload)
        if job is not None:
            publish_job(cfg.publisher, cfg.topic_path, job)
        return 204, b""

    if path == "/process":
        # O serviço é público (o GitHub precisa alcançar o /webhook), então
        # qualquer um poderia forjar um envelope do pub/sub e postar aqui.
        # Só processa se o token OIDC assinado pelo Google for válido.
        auth = h.get("authorization", "") or ""
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        if cfg.verify_oidc(token, cfg.audience) is None:
            return 401, b"unauthorized"
        try:
            job = decode_push(json.loads(body or b"{}"))
        except (json.JSONDecodeError, ValueError, binascii.Error):
            return 400, b"invalid envelope"
        plan_review(job, cfg.provider, cfg.token_fn(), cfg.tasks_client,
                    cfg.chunk_queue_path, cfg.chunk_url, cfg.oidc_sa,
                    cfg.audience, cfg.bot_login)
        return 204, b""

    if path == "/chunk":
        # Cloud Tasks entrega o chunk como JSON cru (não é envelope pub/sub);
        # a validação OIDC é a mesma.
        auth = h.get("authorization", "") or ""
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        if cfg.verify_oidc(token, cfg.audience) is None:
            return 401, b"unauthorized"
        try:
            chunk = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return 400, b"invalid json"
        process_chunk(chunk, cfg.provider, cfg.token_fn(), cfg.bot_login)
        return 204, b""

    return 404, b"not found"


# Emissores aceitos para tokens OIDC do Google (Pub/Sub e Cloud Tasks).
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


def _google_verify(token: str, audience: str) -> dict:
    from google.oauth2 import id_token
    from google.auth.transport import requests as gauth_requests
    return id_token.verify_oauth2_token(token, gauth_requests.Request(),
                                        audience=audience)


def verify_oidc(token: str, audience: str, expected_email: str,
                verify=_google_verify) -> dict | None:
    """Valida assinatura, expiração e audience (verify) E quem assinou.
    Só audience não basta: qualquer SA de qualquer projeto consegue um token
    do Google com o audience do seu serviço. O e-mail tem que ser a SA do
    Pub/Sub/Cloud Tasks deste projeto."""
    try:
        claims = verify(token, audience)
    except Exception:
        return None
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        return None
    if claims.get("email") != expected_email or not claims.get("email_verified"):
        return None
    return claims


class Cfg:
    """Config runtime do serviço: lê env vars no arranque. Em produção elas
    nascem do Terraform (Secret Manager para os segredos)."""

    def __init__(self, provider):
        self.secret = os.environ["GITHUB_WEBHOOK_SECRET"]  # HMAC do webhook
        self.topic_path = os.environ["PUBSUB_TOPIC"]       # topic do pub/sub
        self.provider = provider
        if self.topic_path == "stdout":
            # Modo local: só o /webhook, job impresso no terminal. Nada de GCP.
            self.publisher = StdoutPublisher()
            self.tasks_client = None
            self.chunk_queue_path = self.chunk_url = self.oidc_sa = ""
            self.audience = self.bot_login = ""
            return
        self.chunk_queue_path = os.environ["CHUNK_QUEUE"]  # fila do cloud tasks
        self.chunk_url = os.environ["CHUNK_URL"]           # url pública da rota /chunk
        self.oidc_sa = os.environ["OIDC_SA"]               # SA que assina o OIDC das tasks
        self.audience = os.environ["PROCESS_AUDIENCE"]     # audience esperado na validação
        # Slug REAL do bot (ex.: meu-app[bot]). Tem que bater com o autor dos
        # comentários, senão as guardas de idempotência nunca casam e todo
        # retry duplica o review.
        self.bot_login = os.environ["GH_BOT_LOGIN"]
        from google.cloud import pubsub_v1, tasks_v2
        self.publisher = pubsub_v1.PublisherClient()
        self.tasks_client = tasks_v2.CloudTasksClient()

    def token_fn(self) -> str:
        # Installation token expira em ~1h; instância quente reusaria token
        # morto. Re-minta a cada processamento.
        return mint_installation_token(
            os.environ["GH_APP_ID"],
            os.environ["GH_APP_INSTALLATION_ID"],
            os.environ["GH_APP_PRIVATE_KEY"])

    def verify_oidc(self, token: str, audience: str) -> dict | None:
        return verify_oidc(token, audience, self.oidc_sa)


def serve(port: int, cfg) -> None:  # pragma: no cover - loop de socket
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            import traceback
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            hdrs = {k: v for k, v in self.headers.items()}
            try:
                status, out = handle_request(cfg, self.path, hdrs, body)
            except Exception:  # loga e devolve 500 (pub/sub re-tenta)
                traceback.print_exc()
                status, out = 500, b"internal error"
            self.send_response(status)
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    print(f"agent-scan ouvindo em :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
