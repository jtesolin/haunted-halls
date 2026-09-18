# D5A: Cloud Run deployment permissions for CD service accounts
# Principle: Least privilege, resource-level roles only

# Grant Cloud Run Developer to frontend deployer on the frontend service
# Allows updating frontend service image during CD deployment; Terraform owns other configuration (scaling, env vars, probes, mounts, etc).
resource "google_cloud_run_v2_service_iam_member" "frontend_deployer" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_staging_deployer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend_staging[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

# Centralized production promotion is owned by the frontend repository workflow.
resource "google_cloud_run_v2_service_iam_member" "frontend_deployer_engine_promotion" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "engine_staging_service_deployer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine_staging[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.engine_deployer.email}"
}

resource "google_cloud_run_v2_job_iam_member" "migration_staging_deployer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migration_staging[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.engine_deployer.email}"
}

resource "google_cloud_run_v2_job_iam_member" "frontend_deployer_migration_promotion" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migration.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.frontend_deployer.email}"
}
