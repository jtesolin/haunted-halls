resource "google_service_account" "frontend_runtime" {
  account_id   = local.runtime_service_accounts.frontend
  display_name = "Haunted Halls frontend runtime service account"
  description  = "Future Cloud Run frontend identity for app runtime access."
}

resource "google_service_account" "engine_runtime" {
  account_id   = local.runtime_service_accounts.engine
  display_name = "Haunted Halls engine runtime service account"
  description  = "Future Cloud Run engine identity for database and secret access."
}

resource "google_service_account" "migration_runtime" {
  account_id   = local.runtime_service_accounts.migrate
  display_name = "Haunted Halls migration runtime service account"
  description  = "Future database migration identity for Cloud SQL and deployment secrets."
}

resource "google_service_account" "frontend_staging_runtime" {
  account_id   = local.runtime_service_accounts.frontend_staging
  display_name = "Haunted Halls staging frontend runtime service account"
  description  = "Cloud Run staging frontend identity for app runtime access."
}

resource "google_service_account" "engine_staging_runtime" {
  account_id   = local.runtime_service_accounts.engine_staging
  display_name = "Haunted Halls staging engine runtime service account"
  description  = "Cloud Run staging engine identity for database and secret access."
}

resource "google_service_account" "migration_staging_runtime" {
  account_id   = local.runtime_service_accounts.migrate_staging
  display_name = "Haunted Halls staging migration runtime service account"
  description  = "Staging database migration identity for Cloud SQL and deployment secrets."
}

resource "google_service_account" "frontend_deployer" {
  account_id   = local.deployment_service_accounts.frontend
  display_name = "Haunted Halls frontend deployer service account"
  description  = "GitHub Actions deployer identity for the haunted-halls repository."
}

resource "google_service_account" "engine_deployer" {
  account_id   = local.deployment_service_accounts.engine
  display_name = "Haunted Halls engine deployer service account"
  description  = "GitHub Actions deployer identity for the haunted-halls-engine repository."
}

resource "google_service_account" "production_promoter" {
  account_id   = local.deployment_service_accounts.production_promoter
  display_name = "Haunted Halls production promoter service account"
  description  = "GitHub Actions identity for manual Haunted Halls production promotion."
}

output "runtime_service_account_frontend_email" {
  value = google_service_account.frontend_runtime.email
}

output "runtime_service_account_engine_email" {
  value = google_service_account.engine_runtime.email
}

output "runtime_service_account_migration_email" {
  value = google_service_account.migration_runtime.email
}

output "runtime_service_account_frontend_staging_email" {
  value = google_service_account.frontend_staging_runtime.email
}

output "runtime_service_account_engine_staging_email" {
  value = google_service_account.engine_staging_runtime.email
}

output "runtime_service_account_migration_staging_email" {
  value = google_service_account.migration_staging_runtime.email
}

output "deployment_service_account_frontend_email" {
  value = google_service_account.frontend_deployer.email
}

output "deployment_service_account_engine_email" {
  value = google_service_account.engine_deployer.email
}

output "deployment_service_account_production_promoter_email" {
  value = google_service_account.production_promoter.email
}
