# IAM bindings for Cloud SQL and Secret Manager access
# Principle: Least privilege, secret-level and resource-level bindings only

# Secret Manager: hh-database-url
# Accessed by: engine runtime, migration runtime
resource "google_secret_manager_secret_iam_member" "database_url_engine" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.engine_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url_migration" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migration_runtime.email}"
}

# Secret Manager: hh-internal-engine-service-token
# Accessed by: frontend runtime, engine runtime
resource "google_secret_manager_secret_iam_member" "internal_service_token_frontend" {
  secret_id = google_secret_manager_secret.internal_service_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.frontend_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "internal_service_token_engine" {
  secret_id = google_secret_manager_secret.internal_service_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.engine_runtime.email}"
}

# Secret Manager: hh-nextauth-secret
# Accessed by: frontend runtime only
resource "google_secret_manager_secret_iam_member" "nextauth_secret_frontend" {
  secret_id = google_secret_manager_secret.nextauth_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.frontend_runtime.email}"
}

# Secret Manager: hh-openai-api-key
# Accessed by: engine runtime only
resource "google_secret_manager_secret_iam_member" "openai_api_key_engine" {
  secret_id = google_secret_manager_secret.openai_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.engine_runtime.email}"
}

# Secret Manager: hh-google-client-secret
# Accessed by: frontend runtime only
resource "google_secret_manager_secret_iam_member" "google_client_secret_frontend" {
  secret_id = google_secret_manager_secret.google_client_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.frontend_runtime.email}"
}

# Cloud SQL Client role: engine runtime
# Allows Cloud SQL connector-based access to the database
resource "google_project_iam_member" "engine_cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.engine_runtime.email}"
}

# Cloud SQL Client role: migration runtime
# Allows Cloud SQL connector-based access for schema migrations
resource "google_project_iam_member" "migration_cloud_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.migration_runtime.email}"
}

# Explicit verification: frontend should NOT have Cloud SQL access
# (This is a defensive check; no binding is created intentionally)
# The frontend runtime must access the database only through the engine API
