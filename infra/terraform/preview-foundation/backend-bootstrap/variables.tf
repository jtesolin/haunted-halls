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
