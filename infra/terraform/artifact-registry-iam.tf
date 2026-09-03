# D5A: Artifact Registry push permissions for deployment service accounts
# Principle: Least privilege at repository level, not project-wide

# Grant Artifact Registry Writer to frontend deployer
# Allows pushing, tagging, and managing images for CD workflows
resource "google_artifact_registry_repository_iam_member" "frontend_deployer_writer" {
  repository = google_artifact_registry_repository.app.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

# Grant Artifact Registry Writer to engine deployer
# Allows pushing, tagging, and managing images for CD workflows
resource "google_artifact_registry_repository_iam_member" "engine_deployer_writer" {
  repository = google_artifact_registry_repository.app.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.engine_deployer.email}"
}
