# Cloud SQL PostgreSQL 16 instance for Haunted Halls
# Development configuration: ZONAL, db-f1-micro, minimal storage
# Backups disabled for low-cost development environment
# Future production will require HA, automated backups, and PITR

resource "google_sql_database_instance" "postgres" {
  name                = "haunted-halls-postgres"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false

  settings {
    tier = var.cloud_sql_tier
    # PostgreSQL 16 defaults to ENTERPRISE_PLUS when edition is omitted,
    # but shared-core db-f1-micro requires ENTERPRISE.
    edition               = "ENTERPRISE"
    availability_type     = "ZONAL"
    connector_enforcement = "REQUIRED"
    location_preference {
      zone = "${var.region}-b"
    }

    backup_configuration {
      enabled = false
    }

    # Public IPv4 is intentional for the initial Cloud Run/Cloud SQL connector path.
    # connector_enforcement = "REQUIRED" above rejects direct database connections.
    # No authorized_networks blocks are configured, so no IP range is allowlisted.
    ip_configuration {
      ipv4_enabled    = true
      private_network = null
    }

    disk_size       = var.cloud_sql_disk_size
    disk_type       = "PD_SSD"
    disk_autoresize = true
  }

  depends_on = [
    google_project_service.cloud_sql_admin
  ]
}

# Application database
resource "google_sql_database" "haunted_halls" {
  name     = "haunted_halls"
  instance = google_sql_database_instance.postgres.name

  depends_on = [google_sql_database_instance.postgres]
}

# Staging application database on the shared low-cost Cloud SQL instance
resource "google_sql_database" "haunted_halls_staging" {
  name     = "haunted_halls_staging"
  instance = google_sql_database_instance.postgres.name

  depends_on = [google_sql_database_instance.postgres]
}

# Ephemeral password for the application database user
ephemeral "random_password" "db_password" {
  length           = 32
  special          = false
  override_special = ""
}

# Application database user with ephemeral write-only password.
# Cloud SQL grants cloudsqlsuperuser to built-in PostgreSQL users, and that
# membership is NOT managed here: the google_sql_user resource cannot revoke it.
# Removing it requires the supported operator command documented in the README
# (gcloud sql users assign-roles ... --database-roles= --revoke-existing-roles).
resource "google_sql_user" "app" {
  name                = "haunted_halls_app"
  instance            = google_sql_database_instance.postgres.name
  password_wo         = ephemeral.random_password.db_password.result
  password_wo_version = var.database_password_version
}

# Staging application database user with isolated credentials
ephemeral "random_password" "staging_db_password" {
  length           = 32
  special          = false
  override_special = ""
}

# See google_sql_user.app: cloudsqlsuperuser membership is removed by an
# explicit operator command, not by this resource.
resource "google_sql_user" "app_staging" {
  name                = "haunted_halls_staging_app"
  instance            = google_sql_database_instance.postgres.name
  password_wo         = ephemeral.random_password.staging_db_password.result
  password_wo_version = var.staging_database_password_version
}
