resource "google_project_iam_custom_role" "preview_per_pr_secret_preparer" {
  role_id     = "previewPerPrSecretPreparer"
  title       = "Prepare disposable frontend preview secret versions"
  description = "Read container metadata and add/list/get version metadata only for web PR secret containers."
  permissions = [
    "secretmanager.secrets.get",
    "secretmanager.versions.add",
    "secretmanager.versions.get",
    "secretmanager.versions.list",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "secret_preparer_per_pr_secrets" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_per_pr_secret_preparer.name
  member  = "serviceAccount:${google_service_account.secret_preparer.email}"

  condition {
    title       = "Prepare web per-PR secret versions only"
    description = "The trusted preparer validates exact PR and incarnation names; this condition excludes shared and engine secrets."
    expression  = "(resource.type == \"secretmanager.googleapis.com/Secret\" || resource.type == \"secretmanager.googleapis.com/SecretVersion\") && resource.name.startsWith(\"projects/${data.google_project.preview.number}/secrets/hh-web-pr-\")"
  }
}

resource "google_project_iam_custom_role" "preview_secret_preparer_project_reader" {
  role_id     = "previewSecretPreparerProjectReader"
  title       = "Read fixed preview project identity"
  description = "Read project metadata so the preparer can verify the accepted numeric project number."
  permissions = [
    "resourcemanager.projects.get",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "secret_preparer_project_reader" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_secret_preparer_project_reader.name
  member  = "serviceAccount:${google_service_account.secret_preparer.email}"
}

resource "google_project_iam_member" "secret_preparer_quota_consumer" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_quota_consumer.name
  member  = "serviceAccount:${google_service_account.secret_preparer.email}"
}

resource "google_secret_manager_secret_iam_member" "secret_preparer_db_app_password" {
  secret_id = google_secret_manager_secret.preview_app_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.secret_preparer.email}"
}

resource "google_project_iam_custom_role" "preview_secret_ledger_writer" {
  role_id     = "previewSecretLedgerWriter"
  title       = "Read and append preview secret-preparation ledger objects"
  description = "Read and create immutable ledger markers without overwrite or deletion authority."
  permissions = [
    "storage.objects.create",
    "storage.objects.get",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_storage_bucket_iam_member" "secret_preparer_ledger" {
  bucket = google_storage_bucket.secret_preparation_ledger.name
  role   = google_project_iam_custom_role.preview_secret_ledger_writer.name
  member = "serviceAccount:${google_service_account.secret_preparer.email}"

  condition {
    title       = "Secret-preparation ledger namespace only"
    description = "Read and create immutable markers only within the fixed ledger namespace."
    expression  = "resource.type == \"storage.googleapis.com/Object\" && resource.name.startsWith(\"projects/_/buckets/${google_storage_bucket.secret_preparation_ledger.name}/objects/secret-preparation/v1/\")"
  }
}
