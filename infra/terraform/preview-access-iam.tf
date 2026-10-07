locals {
  preview_deployer_email = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"
}

resource "google_project_iam_custom_role" "preview_staging_engine_metadata" {
  project     = var.project_id
  role_id     = "previewStagingEngineMetadataReader"
  title       = "Read staging engine serving revision"
  description = "Named service and revision reads only; no listing, invocation, IAM changes, or runtime mutation."
  permissions = [
    "run.services.get",
    "run.revisions.get",
  ]

  depends_on = [google_project_service.iam]

  lifecycle {
    precondition {
      condition     = var.project_id == "haunted-halls-development" && var.region == "us-east1"
      error_message = "Preview counterpart reads must target the accepted existing project and region only."
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "preview_staging_engine_metadata" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine_staging[0].name
  role     = google_project_iam_custom_role.preview_staging_engine_metadata.name
  member   = "serviceAccount:${local.preview_deployer_email}"
}

resource "google_artifact_registry_repository_iam_member" "preview_source_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.app.location
  repository = google_artifact_registry_repository.app.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${local.preview_deployer_email}"

  lifecycle {
    precondition {
      condition     = var.project_id == "haunted-halls-development" && var.region == "us-east1"
      error_message = "Preview image reads must target the accepted source project and region only."
    }
  }
}
