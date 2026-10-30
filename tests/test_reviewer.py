"""Testes do núcleo do review: prompt, parse, filtro de linhas — sem rede."""
import pytest

from agent_scan.llm.fake import FakeProvider
from agent_scan.models import ReviewComment, ReviewResult
from agent_scan.reviewer import (
    REVIEW_SCHEMA,
    _filter_to_diff,
    build_user_prompt,
    commentable_lines,
    parse_review,
    review_file,
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


def test_review_file_com_fake_filtra_linha():
    raw = ('{"summary":"s","comments":[{"path":"a.py","line":2,"severity":"info","body":"ok"},'
           '{"path":"a.py","line":99,"severity":"info","body":"alucinada"}]}')
    r = review_file("a.py", "@@ -1,1 +1,2 @@\n x\n+y\n", "x\ny\n", FakeProvider(raw))
    assert [c.line for c in r.comments] == [2]



def test_review_schema_fecha_os_dois_niveis():
    item = REVIEW_SCHEMA["properties"]["comments"]["items"]
    assert REVIEW_SCHEMA["additionalProperties"] is False and item["additionalProperties"] is False
    assert set(item["required"]) == {"path", "line", "severity", "body"}
    assert item["properties"]["severity"]["enum"] == ["info", "warning", "error"]


def test_review_file_manda_schema():
    class Spy(FakeProvider):
        def complete(self, system, user, json_schema=None):
            self.schema = json_schema
            return super().complete(system, user)

    s = Spy()
    review_file("a.py", "@@ -1 +1 @@\n+x\n", "x\n", s)
    assert s.schema is REVIEW_SCHEMA
