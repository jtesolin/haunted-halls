resource "google_storage_bucket" "secret_preparation_ledger" {
  project                     = var.preview_project_id
  name                        = "${var.preview_project_id}-pr-secret-ledger"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  labels = {
    app         = "haunted-halls"
    environment = "preview"
    managed_by  = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}
