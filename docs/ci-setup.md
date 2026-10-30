# Deploy automatizado (GitHub Actions)

O workflow [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml)
roda a cada push na `main`: testes → build da imagem → push no Artifact
Registry → `terraform apply`.

## 1. Service account do CI

O Terraform já cria `agent-scan-deployer` (ver `terraform/ci.tf`). Depois do
primeiro `terraform apply` manual, pegue o e-mail dela:

```bash
terraform -chdir=terraform output -raw deployer_sa
```

## 2. Autenticação — chave JSON (provisória)

> ⚠️ A chave é um token estático de longa duração: quem copiar o JSON faz
> deploy no seu projeto até alguém revogar. Ela serve para o primeiro deploy
> automatizado; a aula 13 troca por Workload Identity Federation e apaga a chave.

```bash
gcloud iam service-accounts keys create /tmp/deployer.json \
  --iam-account="$(terraform -chdir=terraform output -raw deployer_sa)"
gh secret set GCP_SA_KEY < /tmp/deployer.json
rm /tmp/deployer.json   # não deixe a chave no disco
```

Nunca commite o JSON. A chave fica só no secret do GitHub.

## 3. Variáveis do repositório

`Settings → Secrets and variables → Actions → Variables` (ou `gh variable set`):

| Variável | Exemplo |
|---|---|
| `GCP_PROJECT` | `meu-projeto` |
| `GCP_REGION` | `us-east1` |
| `TF_STATE_BUCKET` | `meu-projeto-tfstate` |
| `GH_APP_ID` | `123456` |
| `GH_APP_INSTALLATION_ID` | `12345678` |
| `GH_BOT_LOGIN` | `agent-scan[bot]` |
| `PROCESS_AUDIENCE` | `https://agent-scan-PROJECT_NUMBER.us-east1.run.app` |

## 4. Testar

```bash
gh workflow run deploy   # ou um push na main
gh run watch
```
