# D5A: Service Account User permissions for deployment service accounts
# Principle: Least privilege, explicit runtime identity bindings only
# Allows deployers to impersonate runtime identities during Cloud Run deployments

# Grant frontend deployer permission to act as the frontend runtime service account
resource "google_service_account_iam_member" "frontend_deployer_acts_as_frontend_runtime" {
  service_account_id = google_service_account.frontend_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_service_account_iam_member" "frontend_deployer_acts_as_frontend_staging_runtime" {
  service_account_id = google_service_account.frontend_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

# The centralized production promotion workflow runs from the frontend repo and
# updates the production engine and migration job to captured staging digests.
resource "google_service_account_iam_member" "frontend_deployer_acts_as_engine_runtime_for_promotion" {
  service_account_id = google_service_account.engine_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_service_account_iam_member" "frontend_deployer_acts_as_migration_runtime_for_promotion" {
  service_account_id = google_service_account.migration_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.frontend_deployer.email}"
}

resource "google_service_account_iam_member" "engine_deployer_acts_as_engine_staging_runtime" {
  service_account_id = google_service_account.engine_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.engine_deployer.email}"
}

resource "google_service_account_iam_member" "engine_deployer_acts_as_migration_staging_runtime" {
  service_account_id = google_service_account.migration_staging_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.engine_deployer.email}"
}
