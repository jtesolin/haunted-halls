resource "google_project_iam_custom_role" "cloud_sql_connector" {
  provider    = google.existing
  project     = var.existing_project_id
  role_id     = "previewDbProvisionerCloudSqlConnector"
  title       = "Preview database provisioner Cloud SQL connector"
  description = "Connect with the trusted fixed preview DB control-plane identity."
  permissions = [
    "cloudsql.instances.connect",
    "cloudsql.instances.get",
  ]
}

resource "google_project_iam_member" "db_provisioner_cloud_sql" {
  provider = google.existing
  project  = var.existing_project_id
  role     = google_project_iam_custom_role.cloud_sql_connector.name
  member   = "serviceAccount:${google_service_account.db_provisioner.email}"

  condition {
    title       = "Preview provisioner shared Cloud SQL instance"
    description = "Only connect to the existing Haunted Halls PostgreSQL instance."
    expression  = "resource.type == \"sqladmin.googleapis.com/Instance\" && resource.name == \"projects/${var.existing_project_id}/instances/${data.google_sql_database_instance.existing.name}\""
  }
}

resource "google_cloud_run_v2_service" "db_provisioner" {
  provider            = google.existing
  project             = var.existing_project_id
  name                = "hh-preview-db-provisioner"
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.db_provisioner.email
    max_instance_request_concurrency = 1

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [data.google_sql_database_instance.existing.connection_name]
      }
    }

    containers {
      image = var.provisioner_image

      env {
        name  = "DB_HOST"
        value = "/cloudsql/${data.google_sql_database_instance.existing.connection_name}"
      }
      env {
        name  = "DB_PORT"
        value = "5432"
      }
      env {
        name  = "DB_NAME"
        value = "postgres"
      }
      env {
        name  = "DB_USER"
        value = google_sql_user.preview_provisioner.name
      }
      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.preview_provisioner_password.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "256Mi"
        }
        cpu_idle = true
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  depends_on = [
    google_project_iam_member.db_provisioner_cloud_sql,
    google_secret_manager_secret_iam_member.db_provisioner_password,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "deployer_db_provisioner_invoker" {
  provider = google.existing
  project  = var.existing_project_id
  location = var.region
  name     = google_cloud_run_v2_service.db_provisioner.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}
