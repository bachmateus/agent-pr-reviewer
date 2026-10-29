"""Núcleo do review: prompt, parse do JSON e filtro anti-alucinação de linha."""
import json

from agent_scan.models import ReviewComment, ReviewResult

REVIEW_SYSTEM = (
    "Voce e um revisor de codigo senior. Recebe o diff de um Pull Request e "
    "revisa buscando bugs, riscos, mas praticas e problemas de estilo. Seja "
    "objetivo e util; nao invente problemas. Responda em PORTUGUES.\n"
    "\n"
    "Sugestao de codigo: quando houver uma correcao concreta que caiba em UMA "
    "unica linha (exatamente a linha do campo 'line'), inclua no fim do 'body' "
    "um bloco de sugestao aplicavel do GitHub, no formato:\n"
    "```suggestion\n"
    "<codigo corrigido para AQUELA linha>\n"
    "```\n"
    "O conteudo do bloco substitui integralmente a linha comentada, entao "
    "reproduza a linha inteira ja corrigida. NAO use para mudancas de varias "
    "linhas; nesses casos descreva em prosa.\n"
    "\n"
    "'line' deve ser EXATAMENTE o numero de linha mostrado no CONTEUDO COMPLETO "
    "(o prefixo antes do tab) da linha que voce esta comentando — nao estime nem "
    "conte a mao. Comente apenas linhas presentes no diff (lado novo).\n"
    "\n"
    "Quando o CONTEUDO COMPLETO do arquivo for fornecido, use-o como contexto e "
    "NAO especule sobre codigo que voce consegue ler. Se algo so pode ser "
    "confirmado em codigo que NAO foi fornecido, ou nao comente, ou deixe claro "
    "que e uma hipotese a verificar.\n"
    "\n"
    "Sinal > ruido. NAO comente codigo que esta correto — nada de 'isto "
    "funciona' ou 'esta ok'. Prefira poucos comentarios de alto valor; pule "
    "nitpicks. Se nao houver nada relevante a apontar, devolva comments vazio ([]).\n"
    "\n"
    "Severidade: use 'error'/'warning' apenas para problema CONCRETO evidenciado "
    "no codigo fornecido. Se depende de comportamento de runtime que voce NAO "
    "ve, use no maximo 'info' e deixe explicito que e hipotese.\n"
    "\n"
    "Responda APENAS com JSON valido no formato: "
    '{"summary":"<resumo do PR em markdown>","comments":['
    '{"path":"<arquivo>","line":<int>,"severity":"info|warning|error",'
    '"body":"<comentario em markdown>"}]}'
)

SUMMARY_SYSTEM = (
    "Voce e um revisor de codigo senior. Recebe os diffs (patches) de um Pull "
    "Request e escreve um RESUMO conciso em PORTUGUES (markdown) do que o PR "
    "faz e riscos gerais. Nao comente linha a linha. Responda APENAS com JSON "
    'valido: {"summary":"<resumo em markdown>","comments":[]}'
)


def build_user_prompt(files: list[dict]) -> str:
    parts = []
    for f in files:
        parts.append(f"### Arquivo: {f['filename']} ({f.get('status','')})")
        content = f.get("content")
        if content:
            numbered = "\n".join(f"{i}\t{ln}"
                                 for i, ln in enumerate(content.splitlines(), 1))
            parts.append("[CONTEUDO COMPLETO DO ARQUIVO NO PR — cada linha vem "
                         "prefixada com seu numero; use esse numero em 'line']")
            parts.append(numbered)
        parts.append("[DIFF]")
        parts.append(f.get("patch", "") or "(sem diff textual)")
    return "\n".join(parts)


def commentable_lines(patch: str) -> set[int]:
    """Linhas do lado RIGHT (novo) presentes no patch: contexto + adicionadas.
    Reconstruído dos headers de hunk @@ -a,b +c,d @@."""
    lines: set[int] = set()
    right = 0
    for ln in patch.splitlines():
        if ln.startswith("@@"):
            try:
                plus = ln.split("+", 1)[1]
                right = int(plus.split(",", 1)[0].split(" ", 1)[0]) - 1
            except (IndexError, ValueError):
                right = 0
            continue
        if ln.startswith("-") or ln.startswith("\\"):
            continue
        if ln.startswith("+") or ln.startswith(" "):
            right += 1
            lines.add(right)
    return lines


def parse_review(raw: str) -> ReviewResult:
    """Parse tolerante: extrai o maior bloco {...}; item malformado é
    descartado sem derrubar o lote."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("sem JSON na resposta do review")
    data = json.loads(raw[start:end + 1])
    comments = []
    for c in data.get("comments", []):
        try:
            path = c.get("path")
            line = c.get("line")
            if path and line is not None:
                comments.append(ReviewComment(
                    path=str(path), line=int(line),
                    severity=str(c.get("severity", "info")),
                    body=str(c.get("body", ""))))
        except (ValueError, TypeError):
            continue
    return ReviewResult(summary=str(data.get("summary", "")), comments=comments)


def _filter_to_diff(result: ReviewResult, files: list[dict]) -> ReviewResult:
    """Anti-alucinação: descarta comentário em linha fora do diff (o GitHub
    rejeitaria com 422)."""
    allowed = {f["filename"]: commentable_lines(f.get("patch", "")) for f in files}
    kept = [c for c in result.comments if c.line in allowed.get(c.path, set())]
    return ReviewResult(summary=result.summary, comments=kept)


def review_file(path: str, patch: str, content: str | None, provider,
                budget_chars: int = 120_000) -> ReviewResult:
    """Revisa UM arquivo. Acima do orçamento, trunca o conteúdo primeiro e o
    patch por último (é o patch que garante as linhas comentáveis)."""
    patch = patch or ""
    content = content or ""
    if len(patch) + len(content) > budget_chars:
        room = max(0, budget_chars - len(patch))
        content = (content[:room] + "\n... (conteudo truncado)") if room else ""
        if len(patch) > budget_chars:
            patch = patch[:budget_chars] + "\n... (diff truncado)"
    f = {"filename": path, "patch": patch, "status": "modified",
         "content": content or None}
    try:
        raw = provider.complete(REVIEW_SYSTEM, build_user_prompt([f])).text
        return _filter_to_diff(parse_review(raw), [f])
    except ValueError:
        return ReviewResult(summary="", comments=[])


def summarize_pr(files: list[dict], provider,
                 budget_chars: int = 120_000) -> str:
    """Resumo do PR a partir dos patches. 1 chamada barata; fallback = texto cru."""
    parts, used = [], 0
    for f in files:
        p = f.get("patch", "") or ""
        parts.append(f"### {f['filename']}\n{p}")
        used += len(p)
        if used > budget_chars:
            parts.append("... (diffs truncados)")
            break
    raw = provider.complete(SUMMARY_SYSTEM, "\n\n".join(parts)).text
    try:
        return parse_review(raw).summary
    except ValueError:
        return raw
