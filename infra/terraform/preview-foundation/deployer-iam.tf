resource "google_project_iam_member" "deployer_cloud_run_admin" {
  project = var.preview_project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_custom_role" "preview_secret_manager" {
  role_id     = "previewSecretManager"
  title       = "Preview secret metadata and version management"
  description = "Manage preview secret metadata and versions without reading secret payloads or changing secret IAM policies."
  permissions = [
    "secretmanager.secrets.create",
    "secretmanager.secrets.delete",
    "secretmanager.secrets.get",
    "secretmanager.secrets.list",
    "secretmanager.secrets.update",
    "secretmanager.versions.add",
    "secretmanager.versions.disable",
    "secretmanager.versions.enable",
    "secretmanager.versions.destroy",
    "secretmanager.versions.get",
    "secretmanager.versions.list",
  ]
}

resource "google_project_iam_custom_role" "preview_per_pr_secret_iam" {
  role_id     = "previewPerPrSecretIam"
  title       = "Preview per-PR secret IAM policy management"
  description = "Manage IAM policies only on per-PR preview secrets."
  permissions = [
    "secretmanager.secrets.getIamPolicy",
    "secretmanager.secrets.setIamPolicy",
  ]
}

resource "google_project_iam_member" "deployer_secret_manager" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_secret_manager.name
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_per_pr_secret_iam" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_per_pr_secret_iam.name
  member  = "serviceAccount:${google_service_account.deployer.email}"

  condition {
    title       = "Per-PR preview secrets only"
    description = "The deployer can manage IAM policies only for disposable per-PR secrets, not shared foundation credentials."
    expression  = "resource.name.startsWith(\"projects/${var.preview_project_id}/secrets/hh-web-pr-\") || resource.name.startsWith(\"projects/${var.preview_project_id}/secrets/hh-engine-pr-\")"
  }
}

resource "google_storage_bucket_iam_member" "deployer_preview_state" {
  bucket = var.preview_per_pr_state_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "frontend_act_as" {
  service_account_id = google_service_account.frontend_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "engine_act_as" {
  service_account_id = google_service_account.engine_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "migration_act_as" {
  service_account_id = google_service_account.migration_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
