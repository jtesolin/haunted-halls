variable "project_id" {
  description = "Existing Google Cloud project ID for Haunted Halls infrastructure."
  type        = string

  validation {
    condition     = length(trimspace(var.project_id)) > 0
    error_message = "project_id must be provided."
  }
}

variable "region" {
  description = "Primary Google Cloud region for Haunted Halls resources."
  type        = string
  default     = "us-east1"
}

variable "billing_account_id" {
  description = "Billing account ID for the project budget guardrail. Leave blank to skip budget creation when account access is unavailable."
  type        = string
  default     = ""
}

variable "budget_amount" {
  description = "Monthly project budget in USD for the Haunted Halls cost guardrail."
  type        = string
  default     = "20"

  validation {
    condition     = length(trimspace(var.budget_amount)) > 0 && can(parseint(trimspace(var.budget_amount), 10)) && parseint(trimspace(var.budget_amount), 10) > 0
    error_message = "budget_amount must be a positive integer value in USD per month."
  }
}

variable "github_owner" {
  description = "GitHub user or organization that owns the deployment repositories."
  type        = string
  default     = "jtesolin"
}

variable "frontend_repo_name" {
  description = "GitHub repository name for the frontend deployment identity."
  type        = string
  default     = "haunted-halls"
}

variable "engine_repo_name" {
  description = "GitHub repository name for the engine deployment identity."
  type        = string
  default     = "haunted-halls-engine"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier for the database instance."
  type        = string
  default     = "db-f1-micro"
}

variable "cloud_sql_disk_size" {
  description = "Cloud SQL disk size in GB."
  type        = number
  default     = 10
}

variable "database_password_version" {
  description = "Version for database password rotation. Increment to rotate credentials."
  type        = number
  default     = 1
}

variable "internal_service_token_version" {
  description = "Version for internal service token rotation. Increment to rotate credentials."
  type        = number
  default     = 1
}

variable "nextauth_secret_version" {
  description = "Version for NextAuth secret rotation. Increment to rotate credentials."
  type        = number
  default     = 1
}

variable "frontend_image" {
  description = "Immutable container image reference for the frontend Cloud Run service."
  type        = string

  validation {
    condition     = length(trimspace(var.frontend_image)) > 0
    error_message = "frontend_image must be provided."
  }
}

variable "engine_image" {
  description = "Immutable container image reference for the engine service and migration job."
  type        = string

  validation {
    condition     = length(trimspace(var.engine_image)) > 0
    error_message = "engine_image must be provided."
  }
}

variable "google_oauth_client_id" {
  description = "Google OAuth Web Application client ID for the production frontend."
  type        = string

  validation {
    condition     = length(trimspace(var.google_oauth_client_id)) > 0
    error_message = "google_oauth_client_id must be provided."
  }
}

variable "openai_api_key_version" {
  description = "Secret Manager version for the operator-managed OpenAI API key."
  type        = number
  default     = 2

  validation {
    condition     = var.openai_api_key_version > 0 && floor(var.openai_api_key_version) == var.openai_api_key_version
    error_message = "openai_api_key_version must be a positive integer."
  }
}

variable "google_client_secret_version" {
  description = "Secret Manager version for the operator-managed Google OAuth client secret."
  type        = number

  validation {
    condition     = var.google_client_secret_version > 0 && floor(var.google_client_secret_version) == var.google_client_secret_version
    error_message = "google_client_secret_version must be a positive integer."
  }
}
