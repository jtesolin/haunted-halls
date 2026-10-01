variable "preview_project_id" {
  description = "Dedicated, operator-created Google Cloud project for preview runtime and control-plane resources."
  type        = string
  default     = "hh-preview-458395246135"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.preview_project_id))
    error_message = "preview_project_id must be a valid Google Cloud project ID."
  }
}

variable "existing_project_id" {
  description = "Existing Haunted Halls project that owns the shared Cloud SQL instance and trusted DB control plane."
  type        = string

  validation {
    condition     = length(trimspace(var.existing_project_id)) > 0 && var.existing_project_id != var.preview_project_id
    error_message = "existing_project_id must be provided and must differ from preview_project_id."
  }
}

variable "region" {
  description = "Region for preview resources and the shared Cloud SQL instance."
  type        = string
  default     = "us-east1"
}

variable "billing_account_id" {
  description = "Billing account ID used for the preview-project cost budget. Leave empty only when budget creation is unavailable."
  type        = string
  default     = ""
}

variable "budget_amount" {
  description = "Monthly preview-project budget in USD."
  type        = number
  default     = 20

  validation {
    condition     = var.budget_amount > 0 && floor(var.budget_amount) == var.budget_amount
    error_message = "budget_amount must be a positive whole number of dollars."
  }
}

variable "iap_tester_principals" {
  description = "Explicit principals allowed through IAP to preview frontends. An empty list grants no tester access."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for principal in var.iap_tester_principals :
      can(regex("^(user|group):[^[:space:]]+$", principal))
    ])
    error_message = "IAP tester principals must be explicit user:email or group:email principals."
  }
}

variable "preview_per_pr_state_bucket_name" {
  description = "Dedicated GCS bucket for per-preview state. Do not use this bucket for durable preview-foundation state."
  type        = string
  default     = "hh-preview-458395246135-per-pr-tf-state"

  validation {
    condition     = var.preview_per_pr_state_bucket_name != var.preview_foundation_state_bucket_name
    error_message = "Per-PR state must use a bucket separate from durable preview-foundation state."
  }
}

variable "preview_foundation_state_bucket_name" {
  description = "Bucket name reserved for durable foundation state; the preview deployer must never receive access to it."
  type        = string
  default     = "hh-preview-458395246135-foundation-tf-state"
}

variable "provisioner_image" {
  description = "Optional immutable SHA-256 image digest for phase two, after the preview Artifact Registry repository is ready."
  type        = string
  default     = ""

  validation {
    condition = (
      var.provisioner_image == "" ||
      can(regex("^${var.region}-docker\\.pkg\\.dev/${var.preview_project_id}/haunted-halls-preview/db-provisioner@sha256:[0-9a-f]{64}$", var.provisioner_image))
    )
    error_message = "provisioner_image must be empty for phase one or an immutable digest in the preview-only Artifact Registry repository."
  }
}

variable "preview_app_password_version" {
  description = "Write-only secret version rotation for the shared preview application database login."
  type        = number
  default     = 1
}

variable "preview_provisioner_password_version" {
  description = "Write-only secret version rotation for the trusted database provisioner login."
  type        = number
  default     = 1
}
