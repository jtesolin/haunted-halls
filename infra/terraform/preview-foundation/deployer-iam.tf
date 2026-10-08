resource "google_project_iam_member" "deployer_cloud_run_admin" {
  project = var.preview_project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_custom_role" "preview_iap_tester_policy" {
  role_id     = "previewIapTesterPolicy"
  title       = "Manage preview IAP tester policies"
  description = "Read and change IAP service policies; the grant restricts changes to the tester role."
  permissions = [
    "iap.webServices.getIamPolicy",
    "iap.webServices.setIamPolicy",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "deployer_iap_tester_policy" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_iap_tester_policy.name
  member  = "serviceAccount:${google_service_account.deployer.email}"

  condition {
    title       = "Manage only IAP service tester roles"
    description = "Service policies only; PR naming and tester membership are enforced by trusted configuration, not this condition."
    expression  = "resource.type == \"iap.googleapis.com/WebService\" && api.getAttribute(\"iam.googleapis.com/modifiedGrantsByRole\", []).hasOnly([\"roles/iap.httpsResourceAccessor\"])"
  }
}

resource "google_project_iam_custom_role" "preview_quota_consumer" {
  role_id     = "previewQuotaConsumer"
  title       = "Consume preview project API quota"
  description = "Use the preview quota project without API enablement or quota administration."
  permissions = [
    "serviceusage.services.use",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "deployer_quota_consumer" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_quota_consumer.name
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_custom_role" "preview_per_pr_secret_creator" {
  role_id     = "previewPerPrSecretCreator"
  title       = "Create preview project secret containers"
  description = "Creation only, authorized on the parent project; trusted configuration restricts requested names."
  permissions = [
    "secretmanager.secrets.create",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "deployer_per_pr_secret_creator" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_per_pr_secret_creator.name
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_custom_role" "preview_per_pr_secret_lifecycle" {
  role_id     = "previewPerPrSecretLifecycle"
  title       = "Manage disposable PR secret containers"
  description = "Reconcile Terraform-owned parent metadata and IAM, and delete parents at teardown; no version authority."
  permissions = [
    "secretmanager.secrets.get",
    "secretmanager.secrets.update",
    "secretmanager.secrets.delete",
    "secretmanager.secrets.getIamPolicy",
    "secretmanager.secrets.setIamPolicy",
  ]

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_project_iam_member" "deployer_per_pr_secret_lifecycle" {
  project = var.preview_project_id
  role    = google_project_iam_custom_role.preview_per_pr_secret_lifecycle.name
  member  = "serviceAccount:${google_service_account.deployer.email}"

  condition {
    title       = "Disposable PR parent secrets only"
    description = "Parent-container metadata, IAM and teardown within the web/engine PR namespaces only."
    expression  = "resource.type == \"secretmanager.googleapis.com/Secret\" && (resource.name.startsWith(\"projects/${data.google_project.preview.number}/secrets/hh-web-pr-\") || resource.name.startsWith(\"projects/${data.google_project.preview.number}/secrets/hh-engine-pr-\"))"
  }
}

data "google_storage_bucket" "preview_per_pr_state" {
  name = local.preview_per_pr_state_bucket_name
}

resource "google_storage_bucket_iam_member" "deployer_preview_state" {
  bucket = local.preview_per_pr_state_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"

  lifecycle {
    precondition {
      condition     = tostring(data.google_storage_bucket.preview_per_pr_state.project_number) == tostring(data.google_project.preview.number)
      error_message = "The per-PR state bucket must be owned by the dedicated preview project."
    }
  }
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
