# Fila do fan-out (1 task por arquivo). O que o Pub/Sub não dá: controle de
# vazão — despacha no máximo max_concurrent_dispatches em paralelo pro /chunk,
# casando com max_instances do Cloud Run. Sem 500/429 de saturação no LLM.
resource "google_cloud_tasks_queue" "pr_review_chunks" {
  name       = "pr-review-chunks"
  location   = var.region
  depends_on = [google_project_service.apis]

  rate_limits {
    max_concurrent_dispatches = var.max_instances
    max_dispatches_per_second = 10
  }

  retry_config {
    max_attempts = 6
    min_backoff  = "10s"
    max_backoff  = "600s"
  }
  # Sem DLQ aqui de propósito: o worker é idempotente por (commit_id, path),
  # então retry é inofensivo e task que estoura max_attempts pode sumir.
}

resource "google_cloud_tasks_queue_iam_member" "service_enqueuer" {
  name     = google_cloud_tasks_queue.pr_review_chunks.name
  location = google_cloud_tasks_queue.pr_review_chunks.location
  role     = "roles/cloudtasks.enqueuer"
  member   = "serviceAccount:${google_service_account.agent_scan.email}"
}

# ARMADILHA DE IAM #2: ao CRIAR a task, a SA referencia a si mesma no
# oidc_token -> precisa de serviceAccountUser (actAs) sobre si mesma.
resource "google_service_account_iam_member" "service_act_as_self" {
  service_account_id = google_service_account.agent_scan.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.agent_scan.email}"
}

# ARMADILHA DE IAM #3: no DISPATCH, quem minta o OIDC token é o service agent
# do Cloud Tasks — precisa de tokenCreator NA SA, senão o dispatch falha em
# silêncio (as tasks retentam até o cap e somem) e o /chunk nunca recebe.
resource "google_service_account_iam_member" "cloudtasks_sa_token_creator" {
  service_account_id = google_service_account.agent_scan.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"
  depends_on         = [google_project_service.apis]
}

# A SA precisa invocar o próprio serviço (entregas OIDC do Pub/Sub e do
# Cloud Tasks chegam autenticadas como ela).
resource "google_cloud_run_v2_service_iam_member" "service_self_invoker" {
  project  = google_cloud_run_v2_service.agent_scan.project
  location = google_cloud_run_v2_service.agent_scan.location
  name     = google_cloud_run_v2_service.agent_scan.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.agent_scan.email}"
}
