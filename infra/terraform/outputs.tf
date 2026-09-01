# D4B infrastructure outputs
# Safe outputs for Cloud SQL and Secret Manager
# NOTE: Secret values are intentionally NOT output (never stored in state)

output "cloud_sql_instance_name" {
  description = "Cloud SQL PostgreSQL instance name"
  value       = google_sql_database_instance.postgres.name
}

output "cloud_sql_instance_connection_name" {
  description = "Cloud SQL instance connection name for Cloud SQL Auth Proxy/connector"
  value       = google_sql_database_instance.postgres.connection_name
}

output "cloud_sql_database_name" {
  description = "Application database name"
  value       = google_sql_database.haunted_halls.name
}

output "cloud_sql_database_username" {
  description = "Application database user name"
  value       = google_sql_user.app.name
}

output "secret_database_url_id" {
  description = "Secret Manager secret ID for database URL (secret value not output)"
  value       = google_secret_manager_secret.database_url.id
}

output "secret_internal_service_token_id" {
  description = "Secret Manager secret ID for internal service token (secret value not output)"
  value       = google_secret_manager_secret.internal_service_token.id
}

output "secret_nextauth_secret_id" {
  description = "Secret Manager secret ID for NextAuth secret (secret value not output)"
  value       = google_secret_manager_secret.nextauth_secret.id
}

output "secret_openai_api_key_id" {
  description = "Secret Manager secret ID for OpenAI API key (operator will populate)"
  value       = google_secret_manager_secret.openai_api_key.id
}

output "secret_google_client_secret_id" {
  description = "Secret Manager secret ID for Google client secret (operator will populate)"
  value       = google_secret_manager_secret.google_client_secret.id
}
