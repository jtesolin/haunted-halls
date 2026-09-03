resource "google_cloud_run_v2_service" "engine" {
  count = var.application_services_enabled ? 1 : 0

  name                = local.cloud_run_service_names.engine
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.engine_runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    volumes {
      name = "cloudsql"

      cloud_sql_instance {
        instances = [google_sql_database_instance.postgres.connection_name]
      }
    }

    containers {
      image = var.engine_image

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "AI_ENABLED"
        value = "true"
      }

      env {
        name  = "TOOL_REGISTRY_TRANSPORT"
        value = "local"
      }

      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.id
            version = tostring(var.database_password_version)
          }
        }
      }

      env {
        name = "INTERNAL_ENGINE_SERVICE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.internal_service_token.id
            version = tostring(var.internal_service_token_version)
          }
        }
      }

      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.openai_api_key.id
            version = tostring(var.openai_api_key_version)
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 6

        http_get {
          path = "/health"
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  depends_on = [google_project_service.cloud_run]

  lifecycle {
    # D5A: GitHub Actions CD ownership — ignore deployed image revisions.
    # CD workflows update the image attribute directly through Cloud Run API;
    # Terraform manages all other configuration (scaling, env vars, probes, mounts, etc).
    ignore_changes = [
      template[0].containers[0].image
    ]
  }
}

resource "google_cloud_run_v2_service" "frontend" {
  count = var.application_services_enabled ? 1 : 0

  name                = local.cloud_run_service_names.frontend
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.frontend_runtime.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.frontend_image

      ports {
        container_port = 3000
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "ENGINE_BASE_URL"
        value = local.cloud_run_urls.engine
      }

      env {
        name  = "ENGINE_ID_TOKEN_AUDIENCE"
        value = local.cloud_run_urls.engine
      }

      env {
        name  = "NEXTAUTH_URL"
        value = local.cloud_run_urls.frontend
      }

      env {
        name  = "GOOGLE_CLIENT_ID"
        value = var.google_oauth_client_id
      }

      env {
        name = "INTERNAL_ENGINE_SERVICE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.internal_service_token.id
            version = tostring(var.internal_service_token_version)
          }
        }
      }

      env {
        name = "NEXTAUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.nextauth_secret.id
            version = tostring(var.nextauth_secret_version)
          }
        }
      }

      env {
        name = "GOOGLE_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.google_client_secret.id
            version = tostring(var.google_client_secret_version)
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 10
        failure_threshold     = 6

        http_get {
          path = "/api/health"
        }
      }
    }
  }

  depends_on = [google_project_service.cloud_run]

  lifecycle {
    # D5A: GitHub Actions CD ownership — ignore deployed image revisions.
    # CD workflows update the image attribute directly through Cloud Run API;
    # Terraform manages all other configuration (scaling, env vars, probes, etc).
    ignore_changes = [
      template[0].containers[0].image
    ]

    precondition {
      condition     = length(trimspace(var.frontend_image)) > 0
      error_message = "frontend_image is required when application_services_enabled is true."
    }

    precondition {
      condition     = length(trimspace(var.google_oauth_client_id)) > 0
      error_message = "google_oauth_client_id is required when application_services_enabled is true."
    }

    precondition {
      condition     = var.google_client_secret_version > 0 && floor(var.google_client_secret_version) == var.google_client_secret_version
      error_message = "google_client_secret_version must be a positive integer when application_services_enabled is true."
    }
  }
}

resource "google_cloud_run_v2_job" "migration" {
  name                = local.cloud_run_service_names.migrate
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.migration_runtime.email

      volumes {
        name = "cloudsql"

        cloud_sql_instance {
          instances = [google_sql_database_instance.postgres.connection_name]
        }
      }

      containers {
        image   = var.engine_image
        command = ["python"]
        args    = ["-m", "alembic", "upgrade", "head"]

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.id
              version = tostring(var.database_password_version)
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

  depends_on = [google_project_service.cloud_run]

  lifecycle {
    # D5A: GitHub Actions CD ownership — ignore deployed image revisions.
    # CD workflows update the image attribute directly through Cloud Run API;
    # Terraform preserves the migration command (python -m alembic upgrade head).
    ignore_changes = [
      template[0].template[0].containers[0].image
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "engine_frontend_invoker" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.engine[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.frontend_runtime.email}"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public_invoker" {
  count = var.application_services_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}