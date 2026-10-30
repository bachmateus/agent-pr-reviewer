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

## 2. Autenticação — Workload Identity Federation

Sem chave guardada: a cada execução, o GitHub entrega ao job um token OIDC
assinado ("sou o repo X, branch main"); o GCP confere a assinatura e a
condição de `terraform/wif.tf` e devolve uma credencial curta da SA de deploy.

```bash
terraform -chdir=terraform output -raw wif_provider   # -> GCP_WIF_PROVIDER
terraform -chdir=terraform output -raw deployer_sa    # -> GCP_DEPLOYER_SA
```

### Vindo da chave JSON (aula 11)? Apague a chave

Depois do primeiro deploy verde com WIF:

```bash
gh secret delete GCP_SA_KEY
SA=$(terraform -chdir=terraform output -raw deployer_sa)
gcloud iam service-accounts keys list --iam-account="$SA" --managed-by=user
gcloud iam service-accounts keys delete KEY_ID --iam-account="$SA"
```

Chave esquecida no GCP continua válida mesmo sem uso: apagar é parte do passo.

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
| `GCP_WIF_PROVIDER` | `projects/123/locations/global/workloadIdentityPools/github/providers/github-actions` |
| `GCP_DEPLOYER_SA` | `agent-scan-deployer@meu-projeto.iam.gserviceaccount.com` |

## 4. Testar

```bash
gh workflow run deploy   # ou um push na main
gh run watch
```
