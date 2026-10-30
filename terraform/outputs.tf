output "image_repo" {
  description = "Prefixo da imagem: <image_repo>/agent-scan:<tag>"
  value       = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.agent_scan.repository_id}"
}
