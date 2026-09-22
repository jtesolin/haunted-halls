# D5A: Cloud Run deployment permissions for CD service accounts
# Principle: Least privilege, resource-level roles only

resource "google_cloud_run_v2_service_iam_member" "frontend_staging_deployer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend_staging[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "production_promoter_frontend_staging_viewer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend_staging[0].name
  role     = "roles/run.viewer"
  member   = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_cloud_run_v2_service_iam_member" "production_promoter_engine_staging_viewer" {
  count = var.staging_application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine_staging[0].name
  role     = "roles/run.viewer"
  member   = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_cloud_run_v2_service_iam_member" "production_promoter_frontend_developer" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_cloud_run_v2_service_iam_member" "production_promoter_engine_developer" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine[0].name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.production_promoter.email}"
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

resource "google_cloud_run_v2_job_iam_member" "production_promoter_migration_developer" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.migration.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.production_promoter.email}"
}
