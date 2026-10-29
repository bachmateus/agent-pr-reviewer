"""CLI do agent-scan.

  agent-scan review ORG/REPO#NUM   -> revisa um PR agora, direto do terminal
  agent-scan serve --port 8080     -> sobe o serviço (webhook/planner/worker)
"""
import argparse
import os
from pathlib import Path


def _load_env_and_config() -> dict:
    from dotenv import load_dotenv
    import yaml
    load_dotenv()
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
    if not cfg_path.exists():          # fallback: cwd (container copia pra /app)
        cfg_path = Path("config/config.yaml")
    return yaml.safe_load(cfg_path.read_text())


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
    from agent_scan.llm import build_provider
    from agent_scan.reviewer import review_file, summarize_pr
    from agent_scan.webhook import _reviewable

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
    revs = [f for f in files if _reviewable(f["filename"], f.get("status", ""))]
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
    from agent_scan.llm import build_provider
    from agent_scan.webhook import Cfg, serve
    cfg_yaml = _load_env_and_config()
    provider = build_provider(cfg_yaml)
    serve(port, Cfg(provider))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agent-scan")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_review = sub.add_parser("review", help="revisa um PR agora (síncrono)")
    p_review.add_argument("target", help="ORG/REPO#NUMERO")

    p_serve = sub.add_parser("serve", help="sobe o serviço HTTP")
    p_serve.add_argument("--port", type=int, default=8080)

    args = parser.parse_args(argv)
    if args.cmd == "review":
        return cmd_review(args.target)
    return cmd_serve(args.port)


if __name__ == "__main__":
    raise SystemExit(main())
