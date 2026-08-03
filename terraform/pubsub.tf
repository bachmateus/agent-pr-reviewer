# Desacoplamento do webhook: /webhook publica aqui e responde 204 na hora;
# a subscription push entrega no /process com OIDC.
resource "google_pubsub_topic" "pr_review_requests" {
  name       = "pr-review-requests"
  depends_on = [google_project_service.apis]
}

# O serviço PUBLICA neste topic na rota /webhook. Sem publisher aqui, o
# /webhook estoura 500 ao publicar.
resource "google_pubsub_topic_iam_member" "service_publisher" {
  topic  = google_pubsub_topic.pr_review_requests.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.agent_scan.email}"
}

# ARMADILHA DE IAM #1: a subscription push pede ao Pub/Sub para assinar um
# OIDC token como a SA do serviço. Quem de fato MINTA esse token é o service
# agent do Pub/Sub (service-<numero>@gcp-sa-pubsub...), então ELE precisa de
# tokenCreator NA SA — sem isso a subscription dá Permission denied e o
# /process nunca recebe nada.
resource "google_service_account_iam_member" "pubsub_sa_token_creator" {
  service_account_id = google_service_account.agent_scan.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  depends_on         = [google_project_service.apis]
}

resource "google_pubsub_subscription" "pr_review_push" {
  name  = "pr-review-push"
  topic = google_pubsub_topic.pr_review_requests.id

  ack_deadline_seconds       = 600
  message_retention_duration = "86400s"

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.agent_scan.uri}/process"
    oidc_token {
      service_account_email = google_service_account.agent_scan.email
      audience              = var.process_audience
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  # Mensagem envenenada (payload que sempre derruba o /process) iria
  # re-entregar para sempre dentro da retenção de 24h. Após 5 tentativas,
  # desvia para o topic de dead-letter para inspeção manual.
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.pr_review_dead_letter.id
    max_delivery_attempts = 5
  }
}

resource "google_pubsub_topic" "pr_review_dead_letter" {
  name       = "pr-review-dead-letter"
  depends_on = [google_project_service.apis]
}

# Dead-lettering exige que o service agent do Pub/Sub tenha publisher no
# topic de DLQ e subscriber na subscription original — é ele quem faz o
# encaminhamento.
resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  topic  = google_pubsub_topic.pr_review_dead_letter.id
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  subscription = google_pubsub_subscription.pr_review_push.id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
