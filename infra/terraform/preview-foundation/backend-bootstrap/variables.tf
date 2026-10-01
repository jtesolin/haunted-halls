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

variable "state_bucket_name" {
  description = "Globally unique bucket name in the preview project. Defaults to the project ID with a state suffix."
  type        = string
  default     = "hh-preview-458395246135-tf-state"
}
