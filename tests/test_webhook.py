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
        "comment": {"body": "/REVIEW por favor"},
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
