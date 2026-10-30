# Identidade do CI (GitHub Actions). Separada da SA do serviço: quem faz
# deploy não é quem roda o review.
resource "google_service_account" "deployer" {
  account_id   = "agent-scan-deployer"
  display_name = "agent-scan deployer (GitHub Actions)"
}

# O terraform apply do CI gerencia todo o stack, então precisa administrar
# cada tipo de recurso que ele cria. Papéis explícitos em vez de roles/owner —
# mas atenção: projectIamAdmin permite à SA se dar qualquer papel. Na prática,
# quem faz push na main tem poder de dono do projeto. Proteja a branch main.
locals {
  deployer_roles = [
    "roles/run.admin",
    "roles/artifactregistry.admin",
    "roles/pubsub.admin",
    "roles/cloudtasks.admin",
    "roles/secretmanager.admin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/resourcemanager.projectIamAdmin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.objectAdmin", # state no bucket GCS
    "roles/iam.workloadIdentityPoolAdmin",
  ]
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_roles)
  project  = var.project
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

output "deployer_sa" {
  description = "Service account que o GitHub Actions usa para o deploy"
  value       = google_service_account.deployer.email
}
