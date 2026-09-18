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

output "cloud_sql_staging_database_name" {
  description = "Staging application database name"
  value       = google_sql_database.haunted_halls_staging.name
}

output "cloud_sql_staging_database_username" {
  description = "Staging application database user name"
  value       = google_sql_user.app_staging.name
}

output "cloud_sql_database_privilege_hardening_sql" {
  description = "PostgreSQL statements for an operator to run as a privileged database admin after apply to revoke default cross-database CONNECT, grant each application user only its own database, and grant the public schema privileges that are no longer inherited from cloudsqlsuperuser."
  value       = <<-SQL
    -- Run from any database on the instance as a privileged administrator.
    REVOKE CONNECT ON DATABASE ${google_sql_database.haunted_halls.name} FROM PUBLIC;
    REVOKE CONNECT ON DATABASE ${google_sql_database.haunted_halls_staging.name} FROM PUBLIC;
    GRANT CONNECT ON DATABASE ${google_sql_database.haunted_halls.name} TO ${google_sql_user.app.name};
    GRANT CONNECT ON DATABASE ${google_sql_database.haunted_halls_staging.name} TO ${google_sql_user.app_staging.name};

    -- Terraform assigns no Cloud SQL database roles, so the application users do
    -- not inherit cloudsqlsuperuser and the public schema is owned by
    -- pg_database_owner. Each user needs explicit schema privileges before
    -- Alembic can create objects. Run while connected to ${google_sql_database.haunted_halls.name}:
    GRANT USAGE, CREATE ON SCHEMA public TO ${google_sql_user.app.name};

    -- Run while connected to ${google_sql_database.haunted_halls_staging.name}:
    GRANT USAGE, CREATE ON SCHEMA public TO ${google_sql_user.app_staging.name};
  SQL
}

output "secret_database_url_id" {
  description = "Secret Manager secret_id for database URL (secret value not output)"
  value       = google_secret_manager_secret.database_url.secret_id
}

output "secret_internal_service_token_id" {
  description = "Secret Manager secret_id for internal service token (secret value not output)"
  value       = google_secret_manager_secret.internal_service_token.secret_id
}

output "secret_nextauth_secret_id" {
  description = "Secret Manager secret_id for NextAuth secret (secret value not output)"
  value       = google_secret_manager_secret.nextauth_secret.secret_id
}

output "secret_openai_api_key_id" {
  description = "Secret Manager secret_id for OpenAI API key (operator will populate)"
  value       = google_secret_manager_secret.openai_api_key.secret_id
}

output "secret_google_client_secret_id" {
  description = "Secret Manager secret_id for Google client secret (operator will populate)"
  value       = google_secret_manager_secret.google_client_secret.secret_id
}

output "secret_staging_database_url_id" {
  description = "Secret Manager secret_id for staging database URL (secret value not output)"
  value       = google_secret_manager_secret.database_url_staging.secret_id
}

output "secret_staging_internal_service_token_id" {
  description = "Secret Manager secret_id for staging internal service token (secret value not output)"
  value       = google_secret_manager_secret.internal_service_token_staging.secret_id
}

output "secret_staging_nextauth_secret_id" {
  description = "Secret Manager secret_id for staging NextAuth secret (secret value not output)"
  value       = google_secret_manager_secret.nextauth_secret_staging.secret_id
}

output "secret_staging_google_client_secret_id" {
  description = "Secret Manager secret_id for staging Google client secret (operator will populate)"
  value       = google_secret_manager_secret.google_client_secret_staging.secret_id
}

output "frontend_cloud_run_url" {
  description = "Deterministic run.app URL for the public frontend service."
  value       = local.cloud_run_urls.frontend
}

output "engine_cloud_run_url" {
  description = "Deterministic run.app URL for the private engine service."
  value       = local.cloud_run_urls.engine
}

output "frontend_cloud_run_service_name" {
  description = "Cloud Run frontend service name."
  value       = local.cloud_run_service_names.frontend
}

output "engine_cloud_run_service_name" {
  description = "Cloud Run engine service name."
  value       = local.cloud_run_service_names.engine
}

output "migration_cloud_run_job_name" {
  description = "Cloud Run migration job name."
  value       = local.cloud_run_service_names.migrate
}

output "frontend_staging_cloud_run_url" {
  description = "Deterministic run.app URL for the public staging frontend service."
  value       = local.cloud_run_urls.frontend_staging
}

output "engine_staging_cloud_run_url" {
  description = "Deterministic run.app URL for the private staging engine service."
  value       = local.cloud_run_urls.engine_staging
}

output "frontend_staging_cloud_run_service_name" {
  description = "Cloud Run staging frontend service name."
  value       = local.cloud_run_service_names.frontend_staging
}

output "engine_staging_cloud_run_service_name" {
  description = "Cloud Run staging engine service name."
  value       = local.cloud_run_service_names.engine_staging
}

output "migration_staging_cloud_run_job_name" {
  description = "Cloud Run staging migration job name."
  value       = local.cloud_run_service_names.migrate_staging
}

output "tesolin_us_name_servers" {
  description = "Google Cloud DNS authoritative nameservers for tesolin.us."
  value       = google_dns_managed_zone.tesolin_us.name_servers
}
