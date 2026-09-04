locals {
  common_labels = {
    app         = "haunted-halls"
    managed_by  = "terraform"
    environment = "shared"
  }

  artifact_repository_name = "haunted-halls"

  runtime_service_accounts = {
    frontend = "hh-frontend-runtime"
    engine   = "hh-engine-runtime"
    migrate  = "hh-migration-runtime"
  }

  deployment_service_accounts = {
    frontend = "hh-frontend-deployer"
    engine   = "hh-engine-deployer"
  }

  cloud_run_service_names = {
    frontend = "haunted-halls-frontend"
    engine   = "haunted-halls-engine"
    migrate  = "haunted-halls-migrate"
  }

  cloud_run_urls = {
    frontend = "https://${local.cloud_run_service_names.frontend}-${data.google_project.current.number}.${var.region}.run.app"
    engine   = "https://${local.cloud_run_service_names.engine}-${data.google_project.current.number}.${var.region}.run.app"
  }

  # D6C: canonical public frontend URL, preferring the verified custom domain
  # and falling back to the deterministic Cloud Run run.app URL.
  frontend_canonical_url = (
    length(trimspace(var.frontend_custom_domain)) > 0
    ? "https://${trimspace(var.frontend_custom_domain)}"
    : local.cloud_run_urls.frontend
  )
}
