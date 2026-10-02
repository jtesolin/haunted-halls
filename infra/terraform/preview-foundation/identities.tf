resource "google_service_account" "deployer" {
  account_id   = "hh-preview-deployer"
  display_name = "Haunted Halls preview deployer"
  description  = "Trusted default-branch workflows may manage resources only in the dedicated preview project."

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_service_account" "frontend_runtime" {
  account_id   = "hh-preview-frontend"
  display_name = "Haunted Halls preview frontend runtime"

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_service_account" "engine_runtime" {
  account_id   = "hh-preview-engine"
  display_name = "Haunted Halls preview engine runtime"

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_service_account" "migration_runtime" {
  account_id   = "hh-preview-migration"
  display_name = "Haunted Halls preview migration runtime"

  depends_on = [google_project_service.apis["iam.googleapis.com"]]
}

resource "google_service_account" "db_provisioner" {
  provider     = google.existing
  account_id   = "hh-preview-db-provisioner"
  display_name = "Haunted Halls trusted preview database provisioner"
  description  = "Trusted fixed control-plane runtime; not impersonable by preview deployers."
}

data "google_project" "existing" {
  provider   = google.existing
  project_id = var.existing_project_id
}

data "google_sql_database_instance" "existing" {
  provider = google.existing
  name     = "haunted-halls-postgres"
  project  = var.existing_project_id
}
