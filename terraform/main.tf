terraform {
  # State remoto num bucket GCS: o CI e você aplicam sobre o MESMO state.
  # O bucket vem do init: terraform init -backend-config="bucket=SEU-BUCKET"
  backend "gcs" {
    prefix = "agent-scan"
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

data "google_project" "project" {}

locals {
  apis = [
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "pubsub.googleapis.com",
    "cloudtasks.googleapis.com",
    "artifactregistry.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.apis)
  service            = each.value
  disable_on_destroy = false
}

# Identidade única do serviço: publica no Pub/Sub, enfileira no Cloud Tasks,
# assina o OIDC das entregas e lê os secrets.
resource "google_service_account" "agent_scan" {
  account_id   = "agent-scan"
  display_name = "agent-scan (PR reviewer)"
}
