# O serviço HTTP do agent-scan: /webhook, /process e /chunk numa peça só.
resource "google_cloud_run_v2_service" "agent_scan" {
  name       = "agent-scan"
  location   = var.region
  ingress    = "INGRESS_TRAFFIC_ALL"
  depends_on = [google_project_service.apis]

  template {
    service_account = google_service_account.agent_scan.email

    scaling {
      min_instance_count = 0 # scale-to-zero: sem PR, sem custo
      max_instance_count = var.max_instances
    }
    # Quem limita as chamadas simultâneas ao LLM é a fila do Cloud Tasks
    # (max_concurrent_dispatches). Concorrência > 1 aqui deixa vaga para o
    # /webhook entrar mesmo com workers ocupados — com 1, o GitHub recebia
    # 429 e o evento se perdia (ele não reenvia sozinho).
    # LIMITAÇÃO CONHECIDA: webhook e workers ainda dividem CPU/memória e
    # escala. Num pico, o webhook pode atrasar. Solução robusta: um serviço
    # Cloud Run só para o /webhook.
    max_instance_request_concurrency = var.request_concurrency

    # Review de arquivo grande com Opus passa do default de 300s. Casa com
    # DISPATCH_DEADLINE_S do Cloud Tasks (webhook.py).
    timeout = "900s"

    containers {
      image = var.image
      ports {
        container_port = 8080
      }
      resources {
        limits = {
          cpu    = "1000m"
          memory = "1Gi"
        }
      }

      env {
        name  = "PUBSUB_TOPIC"
        value = google_pubsub_topic.pr_review_requests.id
      }
      env {
        name  = "CHUNK_QUEUE"
        value = google_cloud_tasks_queue.pr_review_chunks.id
      }
      env {
        # URL determinística do próprio serviço (referenciar o .uri computado
        # criaria ciclo no Terraform). A auth real é o OIDC validado no /chunk.
        name  = "CHUNK_URL"
        value = "https://agent-scan-${data.google_project.project.number}.${var.region}.run.app/chunk"
      }
      env {
        name  = "OIDC_SA"
        value = google_service_account.agent_scan.email
      }
      env {
        name  = "PROCESS_AUDIENCE"
        value = var.process_audience
      }
      env {
        name  = "GH_APP_ID"
        value = var.github_app_id
      }
      env {
        name  = "GH_APP_INSTALLATION_ID"
        value = var.github_app_installation_id
      }
      env {
        name  = "GH_BOT_LOGIN"
        value = var.gh_bot_login
      }
      env {
        name = "GITHUB_WEBHOOK_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.github_webhook_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GH_APP_PRIVATE_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.github_app_key.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "ANTHROPIC_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.anthropic.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

# O GitHub não autentica no nível de infra do Cloud Run (chama /webhook sem
# OIDC/IAM), então o serviço precisa aceitar invocação pública — senão a
# própria infra rejeita antes de chegar no container. A autenticação real
# fica na aplicação: HMAC no /webhook, OIDC no /process e /chunk.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = google_cloud_run_v2_service.agent_scan.project
  location = google_cloud_run_v2_service.agent_scan.location
  name     = google_cloud_run_v2_service.agent_scan.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "webhook_url" {
  description = "Cole esta URL no campo Webhook do GitHub App"
  value       = "${google_cloud_run_v2_service.agent_scan.uri}/webhook"
}
