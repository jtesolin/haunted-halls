resource "google_storage_bucket" "preview_state" {
  name                        = var.state_bucket_name
  project                     = var.project_id
  location                    = var.region
  storage_class               = "STANDARD"
  force_destroy               = false
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  labels = {
    app        = "haunted-halls"
    managed_by = "terraform"
    purpose    = "preview-tf-state"
  }
}

output "preview_state_bucket" {
  description = "Bucket for preview-foundation and isolated per-preview Terraform states."
  value       = google_storage_bucket.preview_state.name
}
