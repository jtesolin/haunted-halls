locals {
  preview_foundation_state_bucket_name = "${var.preview_project_id}-foundation-tf-state"
  preview_per_pr_state_bucket_name     = "${var.preview_project_id}-per-pr-tf-state"
}
