# D5A: Service Account User permissions for deployment service accounts
# Principle: Least privilege, explicit runtime identity bindings only
# Allows deployers to impersonate runtime identities during Cloud Run deployments

resource "google_service_account_iam_member" "frontend_deployer_acts_as_frontend_staging_runtime" {
  service_account_id = google_service_account.frontend_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_service_account_iam_member" "engine_deployer_acts_as_engine_staging_runtime" {
  service_account_id = google_service_account.engine_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.engine_deployer.email}"
}

resource "google_service_account_iam_member" "production_promoter_acts_as_frontend_runtime" {
  service_account_id = google_service_account.frontend_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_service_account_iam_member" "production_promoter_acts_as_engine_runtime" {
  service_account_id = google_service_account.engine_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_service_account_iam_member" "production_promoter_acts_as_migration_runtime" {
  service_account_id = google_service_account.migration_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.production_promoter.email}"
}

resource "google_service_account_iam_member" "engine_deployer_acts_as_migration_staging_runtime" {
  service_account_id = google_service_account.migration_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.engine_deployer.email}"
}
