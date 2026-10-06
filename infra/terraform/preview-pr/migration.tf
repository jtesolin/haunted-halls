resource "google_cloud_run_v2_job" "migration" {
  project             = local.project_id
  name                = local.migration_name
  location            = local.region
  deletion_protection = false
  labels              = local.labels

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = local.migration_runtime
      timeout         = "600s"
      max_retries     = 0

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [local.cloud_sql_connection]
        }
      }

      containers {
        image   = var.engine_image
        command = ["alembic"]
        args    = ["upgrade", "head"]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.pr["database_url"].id
              version = google_secret_manager_secret_version.database_url.version
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runtime,
    google_secret_manager_secret_version.nextauth,
    google_secret_manager_secret_version.internal_token,
  ]
}
