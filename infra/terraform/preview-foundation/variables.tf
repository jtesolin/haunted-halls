variable "preview_project_id" {
  description = "Fixed, accepted preview project shared with source grants, per-PR resources, and the backend deployer identity; not a multi-project setting."
  type        = string
  default     = "hh-preview-458395246135"

  validation {
    condition     = var.preview_project_id == "hh-preview-458395246135"
    error_message = "preview_project_id must be hh-preview-458395246135 to match the pinned source grants, per-PR resources, and backend deployer identity; alternate projects are not supported."
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

variable "preview_app_password" {
  description = "Operator-generated 64-character hexadecimal password. Keep the same value for planning, applying, and retrying a given preview_app_password_version."
  type        = string
  sensitive   = true
  ephemeral   = true

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.preview_app_password))
    error_message = "preview_app_password must be a 64-character lowercase hexadecimal value."
  }
}

variable "preview_provisioner_password_version" {
  description = "Write-only secret version rotation for the trusted database provisioner login."
  type        = number
  default     = 1
}

variable "preview_provisioner_password" {
  description = "Operator-generated 64-character hexadecimal password. Keep the same value for planning, applying, and retrying a given preview_provisioner_password_version."
  type        = string
  sensitive   = true
  ephemeral   = true

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.preview_provisioner_password))
    error_message = "preview_provisioner_password must be a 64-character lowercase hexadecimal value."
  }
}
