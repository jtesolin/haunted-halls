resource "google_artifact_registry_repository" "preview" {
  location      = var.region
  repository_id = "haunted-halls-preview"
  description   = "Preview-only images; never used by production or staging deployments."
  format        = "DOCKER"

  cleanup_policies {
    id     = "delete-old-preview-images"
    action = "DELETE"

    condition {
      older_than = "30d"
      tag_state  = "UNTAGGED"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  location   = google_artifact_registry_repository.preview.location
  repository = google_artifact_registry_repository.preview.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_custom_role" "preview_tag_cleanup" {
  role_id     = "previewFrontendTagCleanup"
  title       = "Remove disposable preview image tags"
  description = "Tag deletion only; trusted lifecycle code restricts removal to closed frontend PR tags."
  permissions = [
    "artifactregistry.tags.delete",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_artifact_registry_repository_iam_member" "deployer_tag_cleanup" {
  project    = var.preview_project_id
  location   = google_artifact_registry_repository.preview.location
  repository = google_artifact_registry_repository.preview.name
  role       = google_project_iam_custom_role.preview_tag_cleanup.name
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_artifact_registry_repository_iam_member" "control_plane_reader" {
  project    = var.preview_project_id
  location   = google_artifact_registry_repository.preview.location
  repository = google_artifact_registry_repository.preview.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.existing.number}@serverless-robot-prod.iam.gserviceaccount.com"
}
