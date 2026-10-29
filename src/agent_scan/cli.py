"""CLI do agent-scan.

  agent-scan doctor                  -> confere ambiente, config e credenciais
  agent-scan ask "pergunta"          -> uma chamada ao LLM, com tokens e custo
  agent-scan review-diff ARQUIVO     -> revisa ARQUIVO + ARQUIVO.diff, sem GitHub
  agent-scan review ORG/REPO#NUM     -> revisa um PR agora, direto do terminal
  agent-scan serve --port 8080       -> sobe o serviço (webhook/planner/worker)
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

from agent_scan.llm import build_provider


def _load_env_and_config() -> dict:
    from dotenv import load_dotenv
    import yaml
    load_dotenv()
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
    if not cfg_path.exists():          # fallback: cwd (container copia pra /app)
        cfg_path = Path("config/config.yaml")
    return yaml.safe_load(cfg_path.read_text())


def _provider_name(cfg: dict) -> str:
    return os.environ.get("LLM_PROVIDER") or cfg.get("provider", "anthropic")


def _print_cost(provider, cfg: dict) -> None:
    print(f"tokens: entrada {provider.input_tokens} · saída {provider.output_tokens}"
          f" | custo ${provider.cost_usd:.4f} ({_provider_name(cfg)})")


def cmd_doctor(cfg: dict) -> int:
    """Uma linha por checagem. [falta] impede rodar; [aviso] só limita."""
    missing = False

    def report(level: str, msg: str) -> None:
        nonlocal missing
        missing = missing or level == "falta"
        print(f"[{level}] {msg}")

    v = sys.version_info
    report("ok" if v >= (3, 13) else "falta", f"Python {v.major}.{v.minor} (mínimo 3.13)")
    report("ok", f"config carregado (modelo {cfg.get('review_model')})")
    name = _provider_name(cfg)
    if name == "anthropic":
        report("ok" if os.environ.get("ANTHROPIC_API_KEY") else "falta",
               "ANTHROPIC_API_KEY definida")
    elif name == "claude-code":
        report("ok" if shutil.which("claude") else "falta",
               "claude CLI instalado (logado no Claude Code)")
    try:
        build_provider(cfg)
        report("ok", f"provider {name}")
    except Exception as e:  # provider inválido ou SDK sem credencial
        report("falta", f"provider {name}: {e}")
    for k in ("GH_APP_ID", "GH_APP_INSTALLATION_ID", "GH_APP_PRIVATE_KEY"):
        if not os.environ.get(k):
            report("aviso", f"{k} ausente (só necessário a partir da aula 04)")
    return 1 if missing else 0


def cmd_ask(question: str, cfg: dict) -> int:
    provider = build_provider(cfg)
    c = provider.complete("Responda em português, de forma direta.", question)
    print(c.text)
    _print_cost(provider, cfg)
    return 0


def cmd_review_diff(path: str, cfg: dict) -> int:
    """Revisa um arquivo local: ARQUIVO é o conteúdo, ARQUIVO.diff é o patch."""
    from agent_scan.reviewer import review_file

    diff_path = Path(path + ".diff")
    if not diff_path.exists():
        print(f"diff não encontrado: {diff_path}")
        return 2
    content = Path(path).read_text() if Path(path).exists() else None
    provider = build_provider(cfg)
    result = review_file(path, diff_path.read_text(), content, provider)
    print(result.summary)
    for c in result.comments:
        print(f"{c.path}:{c.line} [{c.severity}] {c.body}")
    _print_cost(provider, cfg)
    return 0


def _mint_token() -> str:
    from agent_scan.github_app import mint_installation_token
    return mint_installation_token(
        os.environ["GH_APP_ID"],
        os.environ["GH_APP_INSTALLATION_ID"],
        os.environ["GH_APP_PRIVATE_KEY"])


def cmd_review(target: str) -> int:
    """Fluxo síncrono local: lê o PR, revisa arquivo a arquivo e posta tudo
    num review só. É o 'loop fechado' do artigo, sem fila nem cloud."""
    from agent_scan import pr as pr_api
    from agent_scan.reviewer import review_file, summarize_pr
    from agent_scan.files import reviewable

    org_repo, _, number_s = target.partition("#")
    org, _, repo = org_repo.partition("/")
    if not (org and repo and number_s.isdigit()):
        print("uso: agent-scan review ORG/REPO#NUMERO")
        return 2
    number = int(number_s)

    cfg = _load_env_and_config()
    provider = build_provider(cfg)
    token = _mint_token()

    head_sha = pr_api.get_pr_head(org, repo, number, token)
    files = pr_api.get_pr_files(org, repo, number, token)
    revs = [f for f in files if reviewable(f["filename"], f.get("status", ""))]
    print(f"PR {target}: {len(files)} arquivos, {len(revs)} revisáveis")

    comments = []
    for f in revs:
        content = None
        if f.get("status") != "removed":
            content = pr_api.get_file_content(org, repo, f["filename"], head_sha, token)
        result = review_file(f["filename"], f.get("patch", ""), content, provider)
        comments.extend(result.comments)
        print(f"  {f['filename']}: {len(result.comments)} comentário(s)")

    summary = summarize_pr(revs, provider) if revs \
        else "Sem arquivos de codigo para revisar neste PR."
    pr_api.post_review(org, repo, number, token,
                       summary or "Revisao automatica.", comments)
    print(f"review postado: {len(comments)} comentário(s) | "
          f"{provider.calls} chamada(s) LLM | ${provider.cost_usd:.4f}")
    return 0


def cmd_serve(port: int) -> int:
    from agent_scan.webhook import Cfg, serve
    cfg_yaml = _load_env_and_config()
    provider = build_provider(cfg_yaml)
    serve(port, Cfg(provider))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent-scan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="confere ambiente, config e credenciais")

    p_ask = sub.add_parser("ask", help="faz uma pergunta ao LLM")
    p_ask.add_argument("question")

    p_diff = sub.add_parser("review-diff", help="revisa ARQUIVO + ARQUIVO.diff")
    p_diff.add_argument("path")

    p_review = sub.add_parser("review", help="revisa um PR agora (síncrono)")
    p_review.add_argument("target", help="ORG/REPO#NUMERO")

    p_serve = sub.add_parser("serve", help="sobe o serviço HTTP")
    p_serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor(_load_env_and_config())
    if args.cmd == "ask":
        return cmd_ask(args.question, _load_env_and_config())
    if args.cmd == "review-diff":
        return cmd_review_diff(args.path, _load_env_and_config())
    if args.cmd == "review":
        return cmd_review(args.target)
    return cmd_serve(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
