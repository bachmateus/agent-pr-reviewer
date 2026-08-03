variable "project" {
  description = "ID do projeto GCP"
  type        = string
}

variable "region" {
  description = "Região dos recursos (Cloud Run, Cloud Tasks)"
  type        = string
  default     = "us-east1"
}

variable "image" {
  description = "Imagem do container do agent-scan (ex.: REGIAO-docker.pkg.dev/PROJETO/REPO/agent-scan:latest)"
  type        = string
}

variable "aws_region" {
  description = "Região do Bedrock (litellm)"
  type        = string
  default     = "us-east-1"
}

variable "github_app_id" {
  description = "App ID do GitHub App"
  type        = string
}

variable "github_app_installation_id" {
  description = "Installation ID do GitHub App na organização"
  type        = string
}

variable "gh_bot_login" {
  description = "Slug REAL do bot (ex.: meu-app[bot]). As guardas de idempotência comparam o autor dos comentários com este valor."
  type        = string
}

variable "process_audience" {
  description = "Audience esperado na validação OIDC das rotas /process e /chunk. Use a URL determinística do serviço: https://agent-scan-<PROJECT_NUMBER>.<REGION>.run.app"
  type        = string
}

variable "max_instances" {
  description = "Máximo de instâncias do Cloud Run. Casa de propósito com max_concurrent_dispatches da fila: instâncias × 1 req/instância = chamadas simultâneas no LLM."
  type        = number
  default     = 10
}
