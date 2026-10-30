"""Eval do review: golden set de bugs conhecidos, medindo o que o modelo acha
(recall), o que ele inventa (ruído) e quanto custa. Mudou o prompt? Rode o eval.

Cada caso é uma pasta com:
  before.<ext>    arquivo antes do PR (ausente = arquivo novo)
  after.<ext>     arquivo depois do PR
  expected.json   {"path": "src/x.py", "expected": [{"line": 4, "keyword": "zero"}]}
O patch é gerado do before/after, como o GitHub geraria.
"""
import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from agent_scan.models import ReviewResult
from agent_scan.reviewer import review_file

# O modelo às vezes aponta a linha vizinha do problema; ±1 ainda é acerto.
LINE_TOLERANCE = 1


@dataclass
class Expected:
    line: int
    keyword: str | None = None   # se definido, precisa aparecer no comentário


@dataclass
class Case:
    name: str
    path: str
    content: str
    patch: str
    expected: list[Expected]


@dataclass
class CaseScore:
    name: str
    hits: list[int]     # linhas esperadas que o review encontrou
    misses: list[int]   # linhas esperadas que ficaram sem comentário
    noise: list[int]    # comentários que não correspondem a nada esperado


@dataclass
class Report:
    scores: list[CaseScore]
    recall: float
    noise: int
    cost_usd: float


def _lines(text: str) -> list[str]:
    # Sem \n no fim, a última linha grudaria na seguinte do diff.
    return [ln if ln.endswith("\n") else ln + "\n" for ln in text.splitlines(keepends=True)]


def _patch(before: str, after: str) -> str:
    diff = difflib.unified_diff(_lines(before), _lines(after))
    return "".join(list(diff)[2:])   # tira os headers ---/+++


def load_cases(cases_dir: Path) -> list[Case]:
    cases = []
    for d in sorted(p for p in Path(cases_dir).iterdir() if p.is_dir()):
        meta = json.loads((d / "expected.json").read_text())
        after = next(d.glob("after.*"))
        before = next(d.glob("before.*"), None)
        content = after.read_text()
        cases.append(Case(
            name=d.name, path=meta["path"], content=content,
            patch=_patch(before.read_text() if before else "", content),
            expected=[Expected(**e) for e in meta["expected"]]))
    return cases


def _matches(e: Expected, line: int, body: str) -> bool:
    if abs(line - e.line) > LINE_TOLERANCE:
        return False
    return e.keyword is None or e.keyword.lower() in body.lower()


def score_case(case: Case, result: ReviewResult) -> CaseScore:
    hits, noise = [], []
    for c in result.comments:
        found = [e for e in case.expected if _matches(e, c.line, c.body)]
        if found:
            hits.extend(e.line for e in found if e.line not in hits)
        else:
            noise.append(c.line)
    misses = [e.line for e in case.expected if e.line not in hits]
    return CaseScore(case.name, sorted(hits), misses, noise)


def run_eval(cases: list[Case], provider) -> Report:
    scores = []
    for case in cases:
        result = review_file(case.path, case.patch, case.content, provider)
        scores.append(score_case(case, result))
    expected = sum(len(s.hits) + len(s.misses) for s in scores)
    found = sum(len(s.hits) for s in scores)
    return Report(scores=scores,
                  recall=found / expected if expected else 1.0,
                  noise=sum(len(s.noise) for s in scores),
                  cost_usd=provider.cost_usd)


def format_report(report: Report) -> str:
    lines = []
    for s in report.scores:
        lines.append(f"  {s.name}: acertos {s.hits} · perdidos {s.misses} · ruído {s.noise}")
    lines.append(f"recall {report.recall:.0%} · ruído {report.noise} comentário(s)"
                 f" · custo ${report.cost_usd:.4f}")
    return "\n".join(lines)
