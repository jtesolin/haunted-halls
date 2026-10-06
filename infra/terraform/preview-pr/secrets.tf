resource "google_secret_manager_secret" "pr" {
  for_each  = local.secret_names
  project   = local.project_id
  secret_id = each.value
  labels    = local.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "nextauth" {
  secret                 = google_secret_manager_secret.pr["nextauth"].id
  secret_data_wo         = var.nextauth_secret
  secret_data_wo_version = var.secret_revision
  deletion_policy        = "ABANDON"
}

resource "google_secret_manager_secret_version" "internal_token" {
  secret                 = google_secret_manager_secret.pr["internal_token"].id
  secret_data_wo         = var.internal_engine_service_token
  secret_data_wo_version = var.secret_revision
  deletion_policy        = "ABANDON"
}

resource "google_secret_manager_secret_version" "database_url" {
  secret                 = google_secret_manager_secret.pr["database_url"].id
  secret_data_wo         = var.database_url
  secret_data_wo_version = var.secret_revision
  deletion_policy        = "ABANDON"
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secret_grants
  project   = local.project_id
  secret_id = google_secret_manager_secret.pr[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.member}"
}
