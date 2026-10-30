"""Testes do script de webhook de teste (assina como o GitHub assinaria)."""
import json

from agent_scan.send_webhook import comment_payload, pr_payload, sign
from agent_scan.webhook import select_event, verify_signature


def test_sign_bate_com_verify_signature():
    body = json.dumps(pr_payload("org", "repo", 7)).encode()
    assert verify_signature(body, sign(body, "s3gr3d0"), "s3gr3d0")
    assert not verify_signature(body, sign(body, "outro"), "s3gr3d0")


def test_pr_payload_vira_job():
    job = select_event("pull_request", pr_payload("org", "repo", 7, head_sha="abc"))
    assert job == {"org": "org", "repo": "repo", "number": 7, "head_sha": "abc"}


def test_comment_payload_review_vira_job_forcado():
    job = select_event("issue_comment", comment_payload("org", "repo", 7))
    assert job["force"] is True and job["number"] == 7


def test_pr_payload_sem_sha_deixa_o_planner_buscar_o_head():
    # sha falso faria o planner buscar conteúdo de um commit que não existe.
    job = select_event("pull_request", pr_payload("org", "repo", 7))
    assert job["head_sha"] is None
