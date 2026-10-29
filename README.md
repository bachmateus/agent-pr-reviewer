# agent-scan

Agente revisor de Pull Requests com LLM. Código de exemplo completo do artigo
**"Como construir um Agente revisor de PR com LLM"**.

Quando um PR abre (ou alguém comenta `/review`), o agente lê o diff, revisa
arquivo por arquivo com um LLM e posta um resumo + comentários inline com
severidade e sugestões aplicáveis (` ```suggestion `). Nunca aprova nem
reprova: `event=COMMENT` sempre — o humano decide o merge.

```
GitHub ──webhook (HMAC)──► /webhook ──publish──► Pub/Sub
                                                    │ push + OIDC
                                                    ▼
                                    /process (PLANNER)
                                      · 1 Cloud Task por arquivo revisável
                                      · posta o resumo do PR
                                                    │ Cloud Tasks (máx 10) + OIDC
                                                    ▼
                                    /chunk (WORKER, 1 arquivo por vez)
                                      · conteúdo completo + diff → LLM
                                      · filtro anti-alucinação de linha
                                      · comentários inline no PR
```

## Estrutura

| Módulo | Papel |
|---|---|
| `src/agent_scan/reviewer.py` | prompt, parse tolerante do JSON, filtro de linhas comentáveis, orçamento de contexto |
| `src/agent_scan/pr.py` | API do GitHub via urllib puro (files, reviews, inline, guardas de idempotência) |
| `src/agent_scan/github_app.py` | JWT RS256 → installation token efêmero (~1h) |
| `src/agent_scan/webhook.py` | rotas `/webhook` `/process` `/chunk`, HMAC, OIDC, planner/worker |
| `src/agent_scan/files.py` | filtro de arquivos revisáveis (pula lockfiles, docs, removidos) |
| `src/agent_scan/llm/` | providers de LLM: `anthropic` (SDK oficial), `claude-code` (CLI local), `fake` (testes); custo por `usage` × tabela de preços |
| `src/agent_scan/cli.py` | comandos `doctor`, `ask`, `review-diff`, `review` (locais) e `serve` (serviço) |

## Rodando local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                       # testes sem rede e sem credencial

cp .env.example .env         # escolha o provider e preencha as credenciais
python -m agent_scan doctor  # confere ambiente e credenciais
python -m agent_scan ask "o que é um code review?"
python -m agent_scan review-diff examples/calc.py   # revisa examples/calc.py + .diff
python -m agent_scan review SUA-ORG/SEU-REPO#123    # precisa do GitHub App
```

`LLM_PROVIDER` escolhe quem responde: `anthropic` (API, cobra por token),
`claude-code` (usa o Claude Code logado na máquina — sem API key; logado por
API key, cobra como a API) ou `fake` (resposta fixa, sem LLM).

O comando `review` executa o fluxo completo de forma síncrona (sem fila, sem
cloud): lê o PR, revisa cada arquivo e posta um review com tudo. Imprime o
custo da execução ao final.

## Pré-requisitos

- **GitHub App** da organização com `Pull requests: Read/Write` +
  `Contents: Read` — passo a passo completo em
  [`docs/github-app-setup.md`](docs/github-app-setup.md).
- **LLM**: uma API key da Anthropic (`ANTHROPIC_API_KEY`) **ou** o Claude Code
  instalado e logado (`LLM_PROVIDER=claude-code`). Modelo, teto de tokens e
  tabela de preços ficam em `config/config.yaml`.
- **GCP** (só para o serviço): Cloud Run + Pub/Sub + Cloud Tasks —
  infra completa em [`terraform/`](terraform/).

## Variáveis de ambiente

| Variável | Uso |
|---|---|
| `LLM_PROVIDER` | `anthropic` \| `claude-code` \| `fake` (sobrepõe `provider` do config) |
| `ANTHROPIC_API_KEY` | credencial da Claude API (provider `anthropic`) |
| `GH_APP_ID` / `GH_APP_INSTALLATION_ID` / `GH_APP_PRIVATE_KEY` | GitHub App (mint do token efêmero) |
| `GITHUB_WEBHOOK_SECRET` | HMAC do webhook |
| `PUBSUB_TOPIC` | topic que o `/webhook` publica |
| `CHUNK_QUEUE` / `CHUNK_URL` | fila do Cloud Tasks e URL pública do `/chunk` |
| `OIDC_SA` / `PROCESS_AUDIENCE` | service account e audience da validação OIDC |
| `GH_BOT_LOGIN` | slug real do bot (`seu-app[bot]`) — as guardas de idempotência comparam com ele |

## Infra (Terraform completo em `terraform/`)

O serviço é um Cloud Run com `min_instances=0` (scale-to-zero) e
`max_instances=10` × `concurrency=1`, casado com a fila do Cloud Tasks
(`max_concurrent_dispatches=10`) — o rate limit do LLM é controlado pela
infra, não por semáforo em código. Pub/Sub com retry (10s→600s) e dead-letter
após 5 tentativas. Segredos no Secret Manager.

```bash
cd terraform
terraform init
terraform apply \
  -var project=SEU_PROJETO \
  -var image=REGIAO-docker.pkg.dev/SEU_PROJETO/REPO/agent-scan:latest \
  -var github_app_id=123456 \
  -var github_app_installation_id=12345678 \
  -var gh_bot_login='agent-scan[bot]' \
  -var process_audience=https://agent-scan-PROJECT_NUMBER.REGIAO.run.app
# depois do apply: adicione os valores dos 3 secrets (ver terraform/secrets.tf)
# e cole o output webhook_url no GitHub App
```

As **3 armadilhas de IAM** que custam horas de debug estão comentadas no
próprio código (`terraform/pubsub.tf` e `terraform/cloudtasks.tf`): o service
agent do Pub/Sub precisa de `tokenCreator` na sua SA; a SA precisa de
`serviceAccountUser` sobre si mesma no enqueue; o service agent do Cloud
Tasks precisa de `tokenCreator` no dispatch.

## Licença

MIT — use à vontade.
