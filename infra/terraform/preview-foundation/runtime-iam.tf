resource "google_artifact_registry_repository_iam_member" "runtime_reader" {
  for_each = {
    frontend  = google_service_account.frontend_runtime.email
    engine    = google_service_account.engine_runtime.email
    migration = google_service_account.migration_runtime.email
  }

  location   = google_artifact_registry_repository.preview.location
  repository = google_artifact_registry_repository.preview.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}

resource "google_project_iam_member" "engine_cloud_sql_client" {
  provider = google.existing
  project  = var.existing_project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${google_service_account.engine_runtime.email}"

  condition {
    title       = "Preview engine access to shared Cloud SQL instance"
    description = "Cloud SQL connector access to the one existing shared instance only."
    expression  = "resource.type == \"sqladmin.googleapis.com/Instance\" && resource.name == \"projects/${var.existing_project_id}/instances/${data.google_sql_database_instance.existing.name}\""
  }
}

resource "google_project_iam_member" "migration_cloud_sql_client" {
  provider = google.existing
  project  = var.existing_project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${google_service_account.migration_runtime.email}"

  condition {
    title       = "Preview migration access to shared Cloud SQL instance"
    description = "Cloud SQL connector access to the one existing shared instance only."
    expression  = "resource.type == \"sqladmin.googleapis.com/Instance\" && resource.name == \"projects/${var.existing_project_id}/instances/${data.google_sql_database_instance.existing.name}\""
  }
}

resource "google_secret_manager_secret_iam_member" "engine_app_db_password" {
  secret_id = google_secret_manager_secret.preview_app_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.engine_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "migration_app_db_password" {
  secret_id = google_secret_manager_secret.preview_app_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migration_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "engine_openai" {
  secret_id = google_secret_manager_secret.preview_openai_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.engine_runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "db_provisioner_password" {
  secret_id = google_secret_manager_secret.preview_provisioner_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.db_provisioner.email}"
}

resource "google_project_iam_member" "iap_tester" {
  for_each = var.iap_tester_principals

  project = var.preview_project_id
  role    = "roles/iap.httpsResourceAccessor"
  member  = each.value
}
