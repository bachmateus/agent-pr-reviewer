"""Testes do webhook: HMAC, filtro de eventos, envelope do Pub/Sub."""
import base64
import hashlib
import hmac
import json

from agent_scan.webhook import decode_push, select_event, verify_signature


def _payload_pr(action="opened", draft=False, user_type="User"):
    return {
        "action": action,
        "repository": {"name": "repo", "owner": {"login": "org"}},
        "pull_request": {"number": 7, "draft": draft,
                         "user": {"type": user_type},
                         "head": {"sha": "abc123"}},
    }


def test_select_event_pr_aberto():
    job = select_event("pull_request", _payload_pr())
    assert job == {"org": "org", "repo": "repo", "number": 7, "head_sha": "abc123"}


def test_select_event_ignora_draft_bot_e_outras_actions():
    assert select_event("pull_request", _payload_pr(draft=True)) is None
    assert select_event("pull_request", _payload_pr(user_type="Bot")) is None
    assert select_event("pull_request", _payload_pr(action="synchronize")) is None


def test_select_event_comando_review_forca():
    payload = {
        "action": "created",
        "repository": {"name": "repo", "owner": {"login": "org"}},
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "/REVIEW por favor", "author_association": "MEMBER"},
    }
    job = select_event("issue_comment", payload)
    assert job["force"] is True
    assert job["head_sha"] is None


def test_select_event_comentario_comum_ignorado():
    payload = {
        "action": "created",
        "repository": {"name": "repo", "owner": {"login": "org"}},
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "belo PR!"},
    }
    assert select_event("issue_comment", payload) is None


def test_verify_signature_hmac_real():
    secret, body = "s3gr3d0", b'{"zen": "ok"}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, secret) is True
    assert verify_signature(body, sig, "outro-secret") is False
    assert verify_signature(body, "", secret) is False


def test_decode_push_desembrulha_envelope():
    job = {"org": "org", "repo": "repo", "number": 7}
    envelope = {"message": {"data": base64.b64encode(
        json.dumps(job).encode()).decode()}}
    assert decode_push(envelope) == job


def test_stdout_publisher_imprime_job(capsys):
    from agent_scan.webhook import StdoutPublisher, publish_job
    publish_job(StdoutPublisher(), "stdout", {"org": "o", "number": 1})
    assert 'job publicado: {"org": "o", "number": 1}' in capsys.readouterr().out


_CLOUD_ENV = {"GITHUB_WEBHOOK_SECRET": "s", "PUBSUB_TOPIC": "projects/p/topics/t",
              "CHUNK_QUEUE": "projects/p/locations/l/queues/q", "CHUNK_URL": "https://svc/chunk",
              "OIDC_SA": "sa@p.iam.gserviceaccount.com", "PROCESS_AUDIENCE": "https://svc",
              "GH_BOT_LOGIN": "bot[bot]"}


def test_cfg_local_stdout_nao_cria_clients_do_gcp(monkeypatch):
    # Quem copiou o .env.example tem CHUNK_QUEUE preenchido; sem credencial
    # do GCP o CloudTasksClient quebraria no arranque.
    from agent_scan.webhook import Cfg, StdoutPublisher
    for k, v in {**_CLOUD_ENV, "PUBSUB_TOPIC": "stdout"}.items():
        monkeypatch.setenv(k, v)
    cfg = Cfg(provider=None)
    assert isinstance(cfg.publisher, StdoutPublisher) and cfg.tasks_client is None


def test_cfg_cloud_exige_variaveis_do_planner(monkeypatch):
    # GH_BOT_LOGIN vazio desligaria as guardas de idempotência em silêncio.
    import pytest
    from agent_scan.webhook import Cfg
    for k, v in _CLOUD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GH_BOT_LOGIN")
    with pytest.raises(KeyError, match="GH_BOT_LOGIN"):
        Cfg(provider=None)

def _comment(author_association):
    return {
        "action": "created",
        "repository": {"name": "repo", "owner": {"login": "org"}},
        "issue": {"number": 7, "pull_request": {"url": "..."}},
        "comment": {"body": "/review", "author_association": author_association},
    }


def test_select_event_review_so_de_quem_tem_acesso():
    # Qualquer conta pode comentar em repo público; /review custa LLM.
    for assoc in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert select_event("issue_comment", _comment(assoc)) is not None
    for assoc in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE", None):
        assert select_event("issue_comment", _comment(assoc)) is None


GOOD_CLAIMS = {"iss": "https://accounts.google.com", "email": "sa@p.iam.gserviceaccount.com",
               "email_verified": True, "aud": "https://svc"}


def test_verify_oidc_aceita_token_da_sa_esperada():
    from agent_scan.webhook import verify_oidc
    claims = verify_oidc("tok", "https://svc", "sa@p.iam.gserviceaccount.com",
                         verify=lambda token, audience: dict(GOOD_CLAIMS))
    assert claims["email"] == "sa@p.iam.gserviceaccount.com"


def test_verify_oidc_rejeita_outra_sa_emissor_ou_email_nao_verificado():
    from agent_scan.webhook import verify_oidc
    bad = [{**GOOD_CLAIMS, "email": "intruso@outro.iam.gserviceaccount.com"},
           {**GOOD_CLAIMS, "iss": "https://evil.example.com"},
           {**GOOD_CLAIMS, "email_verified": False}]
    for claims in bad:
        assert verify_oidc("tok", "https://svc", "sa@p.iam.gserviceaccount.com",
                           verify=lambda token, audience, c=claims: c) is None


def test_verify_oidc_assinatura_invalida():
    from agent_scan.webhook import verify_oidc

    def boom(token, audience):
        raise ValueError("Token used too late")
    assert verify_oidc("tok", "https://svc", "sa@x", verify=boom) is None
