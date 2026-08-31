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
}
