"""Testes do eval: replay em cache, carga do golden set e pontuação."""
import json

from agent_scan.evaluation import (
    Case,
    Expected,
    load_cases,
    run_eval,
    score_case,
)
from agent_scan.llm.fake import FakeProvider
from agent_scan.llm.replay import ReplayProvider
from agent_scan.models import ReviewComment, ReviewResult


def test_replay_segunda_chamada_vem_do_cache_sem_custo(tmp_path):
    inner = FakeProvider("resposta")
    inner.complete = _with_cost(inner.complete, 0.5)
    p = ReplayProvider(inner, tmp_path, key_prefix="fake:m")
    assert p.complete("s", "u").cost_usd == 0.5
    c = p.complete("s", "u")
    assert c.text == "resposta" and c.cost_usd == 0.0
    assert (p.hits, p.misses, inner.calls) == (1, 1, 1)
    assert p.cost_usd == 0.5


def test_replay_chave_muda_com_modelo(tmp_path):
    inner = FakeProvider("x")
    ReplayProvider(inner, tmp_path, key_prefix="fake:a").complete("s", "u")
    ReplayProvider(inner, tmp_path, key_prefix="fake:b").complete("s", "u")
    assert inner.calls == 2


def _with_cost(fn, cost):
    def wrapped(system, user, json_schema=None):
        c = fn(system, user, json_schema)
        c.cost_usd = cost
        return c
    return wrapped


def test_load_cases_gera_patch_do_before_after(tmp_path):
    d = tmp_path / "caso_a"
    d.mkdir()
    (d / "before.py").write_text("a = 1\n")
    (d / "after.py").write_text("a = 1\nb = a / 0\n")
    (d / "expected.json").write_text(json.dumps(
        {"path": "src/a.py", "expected": [{"line": 2, "keyword": "zero"}]}))
    [case] = load_cases(tmp_path)
    assert case.name == "caso_a" and case.path == "src/a.py"
    assert "+b = a / 0" in case.patch and case.patch.startswith("@@")
    assert case.expected == [Expected(line=2, keyword="zero")]


def test_load_cases_arquivo_novo_sem_before(tmp_path):
    d = tmp_path / "novo"
    d.mkdir()
    (d / "after.py").write_text("x = 1\n")
    (d / "expected.json").write_text(json.dumps({"path": "x.py", "expected": []}))
    [case] = load_cases(tmp_path)
    assert case.patch.startswith("@@ -0,0 +1")


def _case(expected):
    return Case(name="c", path="a.py", content="", patch="", expected=expected)


def test_score_case_tolera_uma_linha_e_exige_keyword():
    result = ReviewResult("s", [
        ReviewComment("a.py", 11, "error", "Divisão por ZERO aqui"),   # acerta linha 10 (±1)
        ReviewComment("a.py", 30, "info", "nitpick de nome"),          # ruído
        ReviewComment("a.py", 20, "warning", "outra coisa"),           # linha certa, keyword errada
    ])
    s = score_case(_case([Expected(10, "zero"), Expected(20, "sql")]), result)
    assert (s.hits, s.misses, s.noise) == ([10], [20], [30, 20])


def test_run_eval_soma_recall_ruido_e_custo():
    raw = ('{"summary":"s","comments":[{"path":"a.py","line":1,'
           '"severity":"error","body":"bug"}]}')
    case = Case(name="c", path="a.py", content="x\n", patch="@@ -0,0 +1,1 @@\n+x\n",
                expected=[Expected(1), Expected(5)])
    report = run_eval([case], FakeProvider(raw))
    assert report.recall == 0.5 and report.noise == 0 and report.cost_usd == 0.0


def test_replay_nao_guarda_resposta_cortada(tmp_path):
    # Senão, subir review_max_tokens (a correção óbvia) continuaria replaying o corte.
    inner = FakeProvider("{")
    orig = inner.complete

    def cut(system, user, json_schema=None):
        c = orig(system, user, json_schema)
        c.stop_reason = "max_tokens"
        return c

    inner.complete = cut
    p = ReplayProvider(inner, tmp_path, key_prefix="fake:m")
    p.complete("s", "u")
    p.complete("s", "u")
    assert inner.calls == 2 and p.hits == 0


def test_load_cases_arquivo_sem_quebra_de_linha_no_fim(tmp_path):
    from agent_scan.reviewer import commentable_lines
    d = tmp_path / "sem_eol"
    d.mkdir()
    (d / "before.py").write_text("a = 1\nb = 2")
    (d / "after.py").write_text("a = 1\nb = a / 0")
    (d / "expected.json").write_text(json.dumps({"path": "a.py", "expected": [{"line": 2}]}))
    [case] = load_cases(tmp_path)
    assert 2 in commentable_lines(case.patch)


def test_run_eval_resposta_incompleta_conta_como_perdido():
    class Trunc(FakeProvider):
        def complete(self, system, user, json_schema=None):
            c = super().complete(system, user, json_schema)
            c.stop_reason = "max_tokens"
            return c
    case = Case(name="c", path="a.py", content="x\n", patch="@@ -0,0 +1,1 @@\n+x\n",
                expected=[Expected(1)])
    report = run_eval([case], Trunc())
    assert report.recall == 0.0 and report.scores[0].misses == [1]
    assert report.scores[0].incomplete is True
