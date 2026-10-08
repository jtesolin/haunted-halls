resource "google_cloud_run_v2_service" "engine" {
  project              = local.project_id
  name                 = local.engine_name
  location             = local.region
  deletion_protection  = false
  ingress              = "INGRESS_TRAFFIC_ALL"
  invoker_iam_disabled = false
  labels               = local.labels

  template {
    service_account                  = local.engine_runtime
    timeout                          = "300s"
    max_instance_request_concurrency = 20

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [local.cloud_sql_connection]
      }
    }

    containers {
      image = var.engine_image
      ports {
        container_port = 8000
      }
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
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
            secret  = google_secret_manager_secret.pr["database_url"].id
            version = var.database_url_secret_version
          }
        }
      }
      env {
        name = "INTERNAL_ENGINE_SERVICE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pr["internal_token"].id
            version = var.internal_engine_service_token_version
          }
        }
      }
      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = "projects/${local.project_id}/secrets/hh-preview-openai-api-key"
            version = var.preview_openai_version
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

  depends_on = [google_secret_manager_secret_iam_member.runtime]
}

resource "google_cloud_run_v2_service" "frontend" {
  project              = local.project_id
  name                 = local.frontend_name
  location             = local.region
  deletion_protection  = false
  ingress              = "INGRESS_TRAFFIC_ALL"
  iap_enabled          = true
  invoker_iam_disabled = false
  labels               = local.labels

  template {
    service_account                  = local.frontend_runtime
    timeout                          = "300s"
    max_instance_request_concurrency = 20

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
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }

      dynamic "env" {
        for_each = {
          AUTH_MODE                = "iap"
          IAP_EXPECTED_AUDIENCE    = local.iap_audience
          NEXTAUTH_URL             = local.frontend_url
          ENGINE_BASE_URL          = google_cloud_run_v2_service.engine.uri
          ENGINE_ID_TOKEN_AUDIENCE = google_cloud_run_v2_service.engine.uri
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "NEXTAUTH_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pr["nextauth"].id
            version = var.nextauth_secret_version
          }
        }
      }
      env {
        name = "INTERNAL_ENGINE_SERVICE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.pr["internal_token"].id
            version = var.internal_engine_service_token_version
          }
        }
      }
      startup_probe {
        timeout_seconds   = 3
        period_seconds    = 10
        failure_threshold = 6
        http_get {
          path = "/api/auth/providers"
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runtime,
    google_cloud_run_v2_service_iam_member.engine_frontend,
  ]
}
