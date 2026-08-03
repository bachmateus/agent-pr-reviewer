# Configurando o GitHub App na organização

O agent-scan autentica no GitHub via **GitHub App** — nada de PAT: o App
gera tokens efêmeros que expiram em ~1h, sem rotação manual. Este guia cria
e instala o App na sua organização. Você precisa ser **owner/admin da org**.

## 1. Criar o App

`github.com/organizations/SUA-ORG/settings/apps` → **New GitHub App**
(caminho pela UI: org → Settings → Developer settings → GitHub Apps).

Preencha:

| Campo | Valor |
|---|---|
| GitHub App name | `agent-scan` (o slug do bot vira `agent-scan[bot]`) |
| Homepage URL | qualquer URL (ex.: o repo) |
| Webhook → Active | ✅ |
| Webhook URL | `https://SEU-SERVICO.run.app/webhook` (output `webhook_url` do Terraform) |
| Webhook secret | um segredo forte (ex.: `openssl rand -hex 32`) — o MESMO valor vai pro Secret Manager como `github-webhook-secret` |

O secret nunca trafega: o GitHub calcula `HMAC-SHA256(secret, body)` de cada
entrega e manda só a assinatura no header `X-Hub-Signature-256`; o serviço
recalcula e compara. Se rotacionar, atualize os dois lados.

## 2. Permissões (mínimas)

Em **Permissions & events → Repository permissions**:

| Permissão | Acesso | Por quê |
|---|---|---|
| Pull requests | **Read and write** | ler o diff, postar review e comentários |
| Contents | **Read-only** | buscar o conteúdo completo dos arquivos (contexto > diff) |

Nada além disso. Em **Subscribe to events**, marque:

- **Pull request** — dispara o review quando o PR abre
- **Issue comment** — habilita o comando `/review` para re-review

Em "Where can this GitHub App be installed?" escolha **Only on this account**.

## 3. Gerar as credenciais

Depois de criar, na página do App (aba **General**):

1. Anote o **App ID** → variável `GH_APP_ID`.
2. Em **Private keys** → *Generate a private key* → baixa um `.pem`. Esse
   arquivo é a credencial-mestre: vai para o Secret Manager
   (`github-app-key`), nunca para o git.

## 4. Instalar na organização

Aba **Install App** → escolha a org → selecione **All repositories** (ou só
os repos que devem ser revisados) → Install.

O **Installation ID** aparece na URL da página de instalação:
`github.com/organizations/SUA-ORG/settings/installations/<INSTALLATION_ID>`
→ variável `GH_APP_INSTALLATION_ID`.

## 5. Conferir o slug do bot

O login que assina os comentários é `NOME-DO-APP[bot]` (ex.:
`agent-scan[bot]`). Configure exatamente esse valor em `GH_BOT_LOGIN`.

**Isso importa de verdade**: as guardas de idempotência perguntam ao GitHub
"já existe review/comentário DESTE login neste commit?". Se o valor não bater
com o autor real, a guarda nunca casa e todo retry do Pub/Sub/Cloud Tasks
duplica o review no PR.

## 6. Testar

1. Suba a infra (`terraform apply`) e adicione os valores dos secrets
   (instruções em `terraform/secrets.tf`).
2. Abra um PR de teste num repo coberto pela instalação.
3. Em segundos o PR deve receber o resumo do bot; os comentários inline
   chegam em paralelo.
4. Comente `/review` no PR para forçar um review novo.

Debug rápido se nada acontecer:

- **GitHub → App → Advanced → Recent Deliveries**: mostra cada entrega de
  webhook com request/response. `401` = secret diferente dos dois lados;
  `404` = URL errada.
- **Logs do Cloud Run**: evento recebido? job publicado? `unauthorized` no
  `/process` = problema de OIDC/audience (confira `PROCESS_AUDIENCE` e as
  armadilhas de IAM comentadas em `terraform/pubsub.tf` e
  `terraform/cloudtasks.tf`).
