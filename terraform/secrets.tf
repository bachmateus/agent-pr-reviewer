# Segredos no Secret Manager. O Terraform cria só o "envelope"; o VALOR você
# adiciona manualmente depois do apply (nunca em código/estado):
#
#   echo -n "SEU_SECRET" | gcloud secrets versions add github-webhook-secret --data-file=-
#   gcloud secrets versions add github-app-key --data-file=chave-privada.pem
#   echo -n "SUA_APIKEY" | gcloud secrets versions add bedrock-bearer-token --data-file=-

resource "google_secret_manager_secret" "github_webhook_secret" {
  secret_id = "github-webhook-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "github_app_key" {
  secret_id = "github-app-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "bedrock" {
  secret_id = "bedrock-bearer-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# A SA do serviço precisa ler os três.
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = {
    webhook = google_secret_manager_secret.github_webhook_secret.secret_id
    appkey  = google_secret_manager_secret.github_app_key.secret_id
    bedrock = google_secret_manager_secret.bedrock.secret_id
  }
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent_scan.email}"
}
