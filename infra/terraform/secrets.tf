# Secret Manager secrets for Haunted Halls
# Separates Terraform-managed secret generation from operator-supplied credentials

# Ephemeral secret values for generated credentials
ephemeral "random_password" "internal_service_token" {
  length           = 64
  special          = false
  override_special = ""
}

ephemeral "random_password" "nextauth_secret" {
  length           = 64
  special          = false
  override_special = ""
}

# DATABASE_URL secret
# Contains the full PostgreSQL connection string with ephemeral password
resource "google_secret_manager_secret" "database_url" {
  secret_id = "hh-database-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secret_manager]
}

# Construct DATABASE_URL using ephemeral password and Cloud SQL connection name
# Note: This is a local value, not an ephemeral resource
locals {
  database_url_value = "postgresql+psycopg://${google_sql_user.app.name}:${ephemeral.random_password.db_password.result}@/${google_sql_database.haunted_halls.name}?host=/cloudsql/${google_sql_database_instance.postgres.connection_name}"
}

# Create initial version of DATABASE_URL with ephemeral write-only data
resource "google_secret_manager_secret_version" "database_url_initial" {
  secret                 = google_secret_manager_secret.database_url.id
  secret_data_wo         = local.database_url_value
  secret_data_wo_version = var.database_password_version
}

# Internal service token secret (used by frontend and engine for mutual auth)
resource "google_secret_manager_secret" "internal_service_token" {
  secret_id = "hh-internal-engine-service-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secret_manager]
}

# Create initial version with ephemeral write-only data
resource "google_secret_manager_secret_version" "internal_service_token_initial" {
  secret                 = google_secret_manager_secret.internal_service_token.id
  secret_data_wo         = ephemeral.random_password.internal_service_token.result
  secret_data_wo_version = var.internal_service_token_version
}

# NextAuth secret (used by frontend for session encryption)
resource "google_secret_manager_secret" "nextauth_secret" {
  secret_id = "hh-nextauth-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secret_manager]
}

# Create initial version with ephemeral write-only data
resource "google_secret_manager_secret_version" "nextauth_secret_initial" {
  secret                 = google_secret_manager_secret.nextauth_secret.id
  secret_data_wo         = ephemeral.random_password.nextauth_secret.result
  secret_data_wo_version = var.nextauth_secret_version
}

# OpenAI API key secret (operator-supplied, not managed by Terraform data)
resource "google_secret_manager_secret" "openai_api_key" {
  secret_id = "hh-openai-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secret_manager]
}

# Google OAuth client secret (operator-supplied, not managed by Terraform data)
resource "google_secret_manager_secret" "google_client_secret" {
  secret_id = "hh-google-client-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.secret_manager]
}
