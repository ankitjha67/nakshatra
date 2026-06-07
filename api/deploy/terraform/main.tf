# Terraform skeleton for Jyotish Cloud on GCP.
# This provisions the infra; build/push the image separately (see gcp_deploy.sh)
# or wire Cloud Build. Marked TODOs are values you must supply.
#
#   terraform init && terraform apply \
#     -var project_id=YOUR_PROJECT -var image=REGION-docker.pkg.dev/.../jyotish-api:TAG

terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.0" }
  }
}

variable "project_id" { type = string }
variable "region"     { type = string, default = "asia-south1" }
variable "image"      { type = string } # full Artifact Registry image ref
variable "llm_provider" { type = string, default = "vertex" }

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- APIs ---
locals {
  apis = [
    "run.googleapis.com", "secretmanager.googleapis.com",
    "firestore.googleapis.com", "cloudtasks.googleapis.com",
    "aiplatform.googleapis.com", "artifactregistry.googleapis.com",
  ]
}
resource "google_project_service" "svc" {
  for_each = toset(local.apis)
  service  = each.value
  disable_on_destroy = false
}

# --- service account for the Cloud Run service ---
resource "google_service_account" "api" {
  account_id   = "jyotish-api"
  display_name = "Jyotish Cloud API"
}

resource "google_project_iam_member" "roles" {
  for_each = toset([
    "roles/datastore.user",              # Firestore
    "roles/cloudtasks.enqueuer",         # async
    "roles/aiplatform.user",             # Vertex LLM
    "roles/secretmanager.secretAccessor" # secrets
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.api.email}"
}

# --- Firestore (Native) ---
resource "google_firestore_database" "db" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"
  depends_on  = [google_project_service.svc]
}

# --- Cloud Tasks queue (async readings) ---
resource "google_cloud_tasks_queue" "readings" {
  name     = "readings"
  location = var.region
}

# --- secrets (create the versions out-of-band or via TF vars; values are sensitive) ---
resource "google_secret_manager_secret" "admin_api_key" {
  secret_id = "admin-api-key"
  replication { auto {} }
}
resource "google_secret_manager_secret" "internal_token" {
  secret_id = "internal-token"
  replication { auto {} }
}
# TODO: google_secret_manager_secret_version resources to set values, e.g.
# resource "google_secret_manager_secret_version" "admin_v" {
#   secret = google_secret_manager_secret.admin_api_key.id
#   secret_data = var.admin_api_key   # pass via TF_VAR_admin_api_key
# }

# --- Cloud Run v2 service ---
resource "google_cloud_run_v2_service" "api" {
  name     = "jyotish-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.api.email
    scaling { min_instance_count = 0, max_instance_count = 10 }

    containers {
      image = var.image
      resources { limits = { cpu = "1", memory = "512Mi" } }

      env { name = "APP_ENV"          value = "prod" }
      env { name = "LLM_PROVIDER"     value = var.llm_provider }
      env { name = "STORE_BACKEND"    value = "firestore" } # implement FirestoreStore first
      env { name = "FIRESTORE_PROJECT" value = var.project_id }
      env { name = "VERTEX_PROJECT"   value = var.project_id }
      env { name = "VERTEX_LOCATION"  value = var.region }
      env { name = "CLOUD_TASKS_QUEUE" value = google_cloud_tasks_queue.readings.id }
      # WORKER_BASE_URL set after first deploy (self URL); or use a fixed domain.

      env {
        name = "ADMIN_API_KEY"
        value_source { secret_key_ref { secret = google_secret_manager_secret.admin_api_key.secret_id, version = "latest" } }
      }
      env {
        name = "INTERNAL_TOKEN"
        value_source { secret_key_ref { secret = google_secret_manager_secret.internal_token.secret_id, version = "latest" } }
      }
    }
  }
  depends_on = [google_project_iam_member.roles]
}

# public access (tighten if you front it with a gateway / IAP)
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.api.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "service_url" { value = google_cloud_run_v2_service.api.uri }
