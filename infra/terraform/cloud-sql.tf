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
    tier              = var.cloud_sql_tier
    availability_type = "ZONAL"
    location_preference {
      zone = "${var.region}-b"
    }

    backup_configuration {
      enabled = false
    }

    ip_configuration {
      ipv4_enabled    = true
      private_network = null
    }

    disk_size       = var.cloud_sql_disk_size
    disk_type       = "PD_SSD"
    disk_autoresize = true
  }

  depends_on = [
    google_service_account.engine_runtime,
    google_service_account.migration_runtime
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
  password_wo_version = 1
}
