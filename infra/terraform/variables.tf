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
