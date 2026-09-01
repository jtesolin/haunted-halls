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
    tier                  = var.cloud_sql_tier
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

# Ephemeral password for the application database user
ephemeral "random_password" "db_password" {
  length           = 32
  special          = false
  override_special = ""
}

# Application database user with ephemeral write-only password
resource "google_sql_user" "app" {
  name                = "haunted_halls_app"
  instance            = google_sql_database_instance.postgres.name
  password_wo         = ephemeral.random_password.db_password.result
  password_wo_version = var.database_password_version
}
