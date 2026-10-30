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
| `src/agent_scan/evaluation.py` + `eval/golden/` | golden set de bugs conhecidos: recall, ruído e custo do review |
| `src/agent_scan/llm/replay.py` | replay em cache: rodar o eval de novo sem mudar o prompt não custa nada |
| `src/agent_scan/send_webhook.py` | webhook de teste assinado com HMAC (como o GitHub faria) |
| `src/agent_scan/cli.py` | comandos locais (`doctor`, `ask`, `review-diff`, `list-prs`, `files`, `review`, `send-webhook`) e `serve` (serviço) |

## Rodando local

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                       # testes sem rede e sem credencial

cp .env.example .env         # escolha o provider e preencha as credenciais
python -m agent_scan doctor  # confere ambiente e credenciais
python -m agent_scan ask "o que é um code review?"
python -m agent_scan review-diff examples/calc.py   # revisa examples/calc.py + .diff
python -m agent_scan eval                          # mede o review no golden set
python -m agent_scan list-prs SUA-ORG/SEU-REPO      # testa o GitHub App
python -m agent_scan files SUA-ORG/SEU-REPO#123     # arquivos e filtro
python -m agent_scan review SUA-ORG/SEU-REPO#123    # revisa e posta no PR
```

Webhook local, sem GCP (o job é impresso em vez de ir pro Pub/Sub):

```bash
PUBSUB_TOPIC=stdout GITHUB_WEBHOOK_SECRET=teste python -m agent_scan serve --port 8080 &
GITHUB_WEBHOOK_SECRET=teste python -m agent_scan send-webhook SUA-ORG/SEU-REPO#123   # HTTP 204
GITHUB_WEBHOOK_SECRET=errado python -m agent_scan send-webhook SUA-ORG/SEU-REPO#123  # HTTP 401
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

Primeiro deploy (manual):

```bash
export PROJECT=SEU_PROJETO REGION=us-east1
# 1. bucket do state (uma vez só)
gcloud storage buckets create gs://$PROJECT-tfstate --location=$REGION --uniform-bucket-level-access

# 2. infra base + Artifact Registry
cd terraform
terraform init -backend-config="bucket=$PROJECT-tfstate"
terraform apply -target=google_artifact_registry_repository.agent_scan \
  -var project=$PROJECT -var image=placeholder \
  -var github_app_id=123456 -var github_app_installation_id=12345678 \
  -var gh_bot_login='agent-scan[bot]' \
  -var process_audience=https://agent-scan-PROJECT_NUMBER.$REGION.run.app

# 3. imagem
IMAGE=$REGION-docker.pkg.dev/$PROJECT/agent-scan/agent-scan:v1
gcloud auth configure-docker $REGION-docker.pkg.dev
docker build --platform linux/amd64 -t $IMAGE .. && docker push $IMAGE

# 4. resto da infra, com a imagem real
terraform apply -var project=$PROJECT -var image=$IMAGE  # + as mesmas -var do passo 2
# depois do apply: adicione os valores dos 3 secrets (ver terraform/secrets.tf)
# e cole o output webhook_url no GitHub App
```

Deploys seguintes são automáticos: push na `main` → GitHub Actions →
build + `terraform apply`. Setup em [`docs/ci-setup.md`](docs/ci-setup.md).

As **3 armadilhas de IAM** que custam horas de debug estão comentadas no
próprio código (`terraform/pubsub.tf` e `terraform/cloudtasks.tf`): o service
agent do Pub/Sub precisa de `tokenCreator` na sua SA; a SA precisa de
`serviceAccountUser` sobre si mesma no enqueue; o service agent do Cloud
Tasks precisa de `tokenCreator` no dispatch.

## Licença

MIT — use à vontade.
