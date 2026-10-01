resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "iap.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  project            = var.preview_project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service_identity" "iap" {
  provider = google-beta
  project  = var.preview_project_id
  service  = "iap.googleapis.com"

  depends_on = [google_project_service.apis]
}
