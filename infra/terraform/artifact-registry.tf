resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = local.artifact_repository_name
  description   = "Docker images for Haunted Halls frontend and engine workloads."
  format        = "DOCKER"

  labels = merge(local.common_labels, {
    component = "artifact-registry"
  })

  depends_on = [
    google_project_service.artifact_registry,
  ]
}

output "artifact_registry_repository_id" {
  description = "Artifact Registry repository identifier for future image builds and deployments."
  value       = google_artifact_registry_repository.app.repository_id
}

output "artifact_registry_repository_location" {
  description = "Artifact Registry region used for Haunted Halls images."
  value       = google_artifact_registry_repository.app.location
}

output "artifact_registry_repository_path" {
  description = "Repository path to use in future docker tag and deploy automation."
  value       = "${google_artifact_registry_repository.app.location}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}
