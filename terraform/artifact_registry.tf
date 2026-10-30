# Onde mora a imagem do container. O Cloud Run puxa daqui.
resource "google_artifact_registry_repository" "agent_scan" {
  repository_id = "agent-scan"
  location      = var.region
  format        = "DOCKER"
  description   = "Imagens do agent-scan"
  depends_on    = [google_project_service.apis]

  # Sem limpeza, cada deploy deixa uma imagem para trás (e storage custa).
  cleanup_policies {
    id     = "manter-10-mais-recentes"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
  cleanup_policies {
    id     = "apagar-o-resto"
    action = "DELETE"
    condition {
      older_than = "604800s" # 7 dias
    }
  }
}
