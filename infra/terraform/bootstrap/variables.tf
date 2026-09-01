variable "project_id" {
  description = "Existing Google Cloud project ID that will own the Terraform state bucket."
  type        = string
}

variable "region" {
  description = "Region for the state bucket location."
  type        = string
  default     = "us-east1"
}

variable "state_bucket_name" {
  description = "Globally unique storage bucket name for Terraform remote state."
  type        = string
}
