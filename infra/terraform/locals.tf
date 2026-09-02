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
}
