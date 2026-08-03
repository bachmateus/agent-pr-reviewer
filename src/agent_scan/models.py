"""Contrato interno do review."""
from dataclasses import dataclass, field


@dataclass
class ReviewComment:
    path: str        # arquivo comentado
    line: int        # linha do lado novo do diff
    severity: str    # info | warning | error
    body: str        # markdown do comentário


@dataclass
class ReviewResult:
    summary: str
    comments: list[ReviewComment] = field(default_factory=list)
