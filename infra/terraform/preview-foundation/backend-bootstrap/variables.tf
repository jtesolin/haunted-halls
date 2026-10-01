variable "project_id" {
  description = "Dedicated, operator-created Google Cloud preview project."
  type        = string
  default     = "hh-preview-458395246135"
}

variable "region" {
  description = "Preview Terraform state bucket location."
  type        = string
  default     = "us-east1"
}

variable "foundation_state_bucket_name" {
  description = "Globally unique private bucket for durable preview-foundation Terraform state."
  type        = string
  default     = "hh-preview-458395246135-foundation-tf-state"
}

variable "per_pr_state_bucket_name" {
  description = "Globally unique private bucket for isolated per-PR Terraform states."
  type        = string
  default     = "hh-preview-458395246135-per-pr-tf-state"
}
