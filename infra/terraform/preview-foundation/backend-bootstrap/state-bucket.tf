locals {
  foundation_state_bucket_name = "${var.project_id}-foundation-tf-state"
  per_pr_state_bucket_name     = "${var.project_id}-per-pr-tf-state"
}

resource "google_storage_bucket" "foundation_state" {
  name                        = local.foundation_state_bucket_name
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
    purpose    = "preview-foundation-state"
  }
}

resource "google_storage_bucket" "per_pr_state" {
  name                        = local.per_pr_state_bucket_name
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
    purpose    = "preview-per-pr-state"
  }
}

output "preview_foundation_state_bucket" {
  description = "Private bucket for durable preview-foundation state; never writable by the preview deployer."
  value       = google_storage_bucket.foundation_state.name
}

output "preview_per_pr_state_bucket" {
  description = "Private bucket for isolated per-preview Terraform states."
  value       = google_storage_bucket.per_pr_state.name
}
