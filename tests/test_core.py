"""Testes das funções puras do núcleo — rodam sem credencial e sem rede."""
import base64
import hashlib
import hmac
import json

import pytest

from agent_scan.models import ReviewComment, ReviewResult
from agent_scan.reviewer import (
    _filter_to_diff,
    build_user_prompt,
    commentable_lines,
    parse_review,
)
from agent_scan.webhook import (
    _reviewable,
    decode_push,
    select_event,
    verify_signature,
)

PATCH = (
    "@@ -1,3 +1,4 @@\n"
    " linha de contexto\n"
    "-linha removida\n"
    "+linha nova 2\n"
    "+linha nova 3\n"
    " outra de contexto\n"
)


def test_commentable_lines_contexto_e_adicionadas():
    # RIGHT começa em 1: contexto(1), +nova(2), +nova(3), contexto(4)
    assert commentable_lines(PATCH) == {1, 2, 3, 4}


def test_commentable_lines_hunk_sem_virgula():
    assert commentable_lines("@@ -1 +1 @@\n+unica\n") == {1}


def test_commentable_lines_ignora_no_newline():
    patch = "@@ -1 +1 @@\n+fim\n\\ No newline at end of file\n"
    assert commentable_lines(patch) == {1}


def test_parse_review_json_com_prosa_em_volta():
    raw = ('Claro! Aqui está:\n{"summary":"ok","comments":'
           '[{"path":"a.py","line":2,"severity":"warning","body":"cuidado"}]}\nEspero ter ajudado!')
    r = parse_review(raw)
    assert r.summary == "ok"
    assert r.comments == [ReviewComment("a.py", 2, "warning", "cuidado")]


def test_parse_review_descarta_item_malformado():
    raw = ('{"summary":"s","comments":[{"path":"a.py","line":"nao-e-int"},'
           '{"line":3},{"path":"b.py","line":7,"body":"ok"}]}')
    r = parse_review(raw)
    assert [(c.path, c.line, c.severity) for c in r.comments] == [("b.py", 7, "info")]


def test_parse_review_sem_json_levanta():
    with pytest.raises(ValueError):
        parse_review("não tem json aqui")


def test_filter_to_diff_descarta_linha_alucinada():
    files = [{"filename": "a.py", "patch": PATCH}]
    result = ReviewResult(summary="s", comments=[
        ReviewComment("a.py", 2, "info", "válido"),
        ReviewComment("a.py", 99, "error", "linha alucinada"),
        ReviewComment("outro.py", 2, "info", "arquivo fora do PR"),
    ])
    kept = _filter_to_diff(result, files).comments
    assert [(c.path, c.line) for c in kept] == [("a.py", 2)]


def test_build_user_prompt_numera_conteudo():
    prompt = build_user_prompt([{"filename": "a.py", "status": "modified",
                                 "content": "x = 1\ny = 2", "patch": PATCH}])
    assert "1\tx = 1" in prompt
    assert "2\ty = 2" in prompt
    assert "[DIFF]" in prompt


def test_build_user_prompt_sem_patch():
    prompt = build_user_prompt([{"filename": "a.bin", "status": "modified"}])
    assert "(sem diff textual)" in prompt


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


def test_reviewable_filtros():
    assert _reviewable("src/app.py", "modified") is True
    assert _reviewable("README.md", "modified") is False
    assert _reviewable("docs/guia.txt", "modified") is False
    assert _reviewable("package-lock.json", "modified") is False
    assert _reviewable("src/app.py", "removed") is False
