variable "repository_key" {
  type        = string
  description = "Canonical repository namespace; web is haunted-halls, engine is haunted-halls-engine. Engine lifecycle is not implemented here."

  validation {
    condition     = contains(["web", "engine"], var.repository_key)
    error_message = "repository_key must be exactly web or engine."
  }
}

variable "pull_request_number" {
  type        = string
  description = "Canonical positive decimal PR identifier, bounded identically to the trusted DB provisioner."

  validation {
    condition     = can(regex("^[1-9][0-9]{0,8}$", var.pull_request_number))
    error_message = "pull_request_number must be 1..999999999 without leading zeros, signs, whitespace, or fractions."
  }
}

variable "backend_state_prefix" {
  type        = string
  description = "Must match the backend prefix verified by check_backend.py before every stateful operation."

  validation {
    condition     = var.backend_state_prefix == "previews/${var.repository_key}-pr-${var.pull_request_number}"
    error_message = "backend_state_prefix must match the repository/PR identity exactly."
  }
}

variable "pr_incarnation" {
  type        = string
  description = "Trusted immutable 128-bit lowercase-hex ID for one disposable PR preview lifetime."

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.pr_incarnation))
    error_message = "pr_incarnation must be exactly 32 lowercase hexadecimal characters."
  }
}

variable "preview_project_number" {
  type        = string
  description = "Actual numeric project number from accepted foundation metadata, NOT the suffix of the project ID. Verify before live init."

  validation {
    condition     = can(regex("^[1-9][0-9]{0,19}$", var.preview_project_number))
    error_message = "preview_project_number must be the verified positive decimal Google Cloud project number."
  }
}

variable "frontend_image" {
  type        = string
  description = "Accepted immutable PR artifact. 41C must verify PR head/provenance before supplying it."

  validation {
    condition     = can(regex("^us-east1-docker\\.pkg\\.dev/hh-preview-458395246135/haunted-halls-preview/frontend@sha256:[0-9a-f]{64}$", var.frontend_image))
    error_message = "frontend_image must be a lowercase sha256 digest in the preview frontend image repository; tags are forbidden."
  }
}

variable "engine_image" {
  type        = string
  description = "Frozen Ready/serving staging engine artifact; also used verbatim by the migration job."

  validation {
    condition     = can(regex("^us-east1-docker\\.pkg\\.dev/haunted-halls-development/haunted-halls/engine@sha256:[0-9a-f]{64}$", var.engine_image))
    error_message = "engine_image must be a lowercase sha256 digest in the existing engine image repository; tags are forbidden."
  }
}

variable "iap_testers" {
  type        = set(string)
  description = "Explicit Google user or group principals on this frontend's IAP resource only."

  validation {
    condition = length(var.iap_testers) > 0 && alltrue([
      for member in var.iap_testers : can(regex("^(user|group):[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+$", member))
    ])
    error_message = "iap_testers must contain explicit user:email or group:email principals; public/domain/service-account grants are forbidden."
  }
}

variable "preview_openai_version" {
  type        = string
  default     = "1"
  description = "Enabled numeric version of the existing preview-only OpenAI secret; no latest alias."

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.preview_openai_version))
    error_message = "preview_openai_version must be an explicit positive Secret Manager version."
  }
}

variable "nextauth_secret_version" {
  type        = string
  description = "Explicit numeric Secret Manager version returned by the trusted preparer."

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.nextauth_secret_version))
    error_message = "nextauth_secret_version must be an explicit positive numeric version; aliases are forbidden."
  }
}

variable "internal_engine_service_token_version" {
  type        = string
  description = "Explicit numeric Secret Manager version returned by the trusted preparer."

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.internal_engine_service_token_version))
    error_message = "internal_engine_service_token_version must be an explicit positive numeric version; aliases are forbidden."
  }
}

variable "database_url_secret_version" {
  type        = string
  description = "Explicit numeric Secret Manager version returned by the trusted preparer."

  validation {
    condition     = can(regex("^[1-9][0-9]*$", var.database_url_secret_version))
    error_message = "database_url_secret_version must be an explicit positive numeric version; aliases are forbidden."
  }
}
