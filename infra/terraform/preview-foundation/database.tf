resource "google_sql_user" "preview_app" {
  provider            = google.existing
  name                = "haunted_halls_preview_app"
  instance            = data.google_sql_database_instance.existing.name
  password_wo         = var.preview_app_password
  password_wo_version = var.preview_app_password_version
}

resource "google_sql_user" "preview_provisioner" {
  provider            = google.existing
  name                = "haunted_halls_preview_provisioner"
  instance            = data.google_sql_database_instance.existing.name
  password_wo         = var.preview_provisioner_password
  password_wo_version = var.preview_provisioner_password_version
}

resource "google_secret_manager_secret" "preview_app_password" {
  secret_id = "hh-preview-db-app-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "preview_app_password" {
  secret                 = google_secret_manager_secret.preview_app_password.id
  secret_data_wo         = var.preview_app_password
  secret_data_wo_version = var.preview_app_password_version
}

resource "google_secret_manager_secret" "preview_provisioner_password" {
  secret_id = "hh-preview-db-provisioner-password"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "preview_provisioner_password" {
  secret                 = google_secret_manager_secret.preview_provisioner_password.id
  secret_data_wo         = var.preview_provisioner_password
  secret_data_wo_version = var.preview_provisioner_password_version
}

resource "google_secret_manager_secret" "preview_openai_api_key" {
  secret_id = "hh-preview-openai-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "deployer_openai_secret_version_adder" {
  secret_id = google_secret_manager_secret.preview_openai_api_key.id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.deployer.email}"
}
