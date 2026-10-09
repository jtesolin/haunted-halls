resource "google_secret_manager_secret" "pr" {
  for_each  = local.secret_names
  project   = local.project_id
  secret_id = each.value
  labels    = local.secret_labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = local.secret_grants
  project   = local.project_id
  secret_id = google_secret_manager_secret.pr[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.member}"
}
