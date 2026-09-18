locals {
  common_labels = {
    app         = "haunted-halls"
    managed_by  = "terraform"
    environment = "shared"
  }

  artifact_repository_name = "haunted-halls"
  frontend_image_repository = (
    "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repository_name}/frontend"
  )
  engine_image_repository = (
    "${var.region}-docker.pkg.dev/${var.project_id}/${local.artifact_repository_name}/engine"
  )
  staging_frontend_hostname = "staging.haunted-halls.tesolin.us"

  runtime_service_accounts = {
    frontend         = "hh-frontend-runtime"
    engine           = "hh-engine-runtime"
    migrate          = "hh-migration-runtime"
    frontend_staging = "hh-frontend-runtime-staging"
    engine_staging   = "hh-engine-runtime-staging"
    migrate_staging  = "hh-migration-runtime-staging"
  }

  deployment_service_accounts = {
    frontend = "hh-frontend-deployer"
    engine   = "hh-engine-deployer"
  }

  cloud_run_service_names = {
    frontend         = "haunted-halls-frontend"
    engine           = "haunted-halls-engine"
    migrate          = "haunted-halls-migrate"
    frontend_staging = "haunted-halls-frontend-staging"
    engine_staging   = "haunted-halls-engine-staging"
    migrate_staging  = "haunted-halls-migrate-staging"
  }

  cloud_run_urls = {
    frontend         = "https://${local.cloud_run_service_names.frontend}-${data.google_project.current.number}.${var.region}.run.app"
    engine           = "https://${local.cloud_run_service_names.engine}-${data.google_project.current.number}.${var.region}.run.app"
    frontend_staging = "https://${local.cloud_run_service_names.frontend_staging}-${data.google_project.current.number}.${var.region}.run.app"
    engine_staging   = "https://${local.cloud_run_service_names.engine_staging}-${data.google_project.current.number}.${var.region}.run.app"
  }

  # D6C: canonical public frontend URL, preferring the verified custom domain
  # and falling back to the deterministic Cloud Run run.app URL.
  frontend_canonical_url = (
    length(trimspace(var.frontend_custom_domain)) > 0
    ? "https://${trimspace(var.frontend_custom_domain)}"
    : local.cloud_run_urls.frontend
  )

  staging_frontend_canonical_url = "https://${local.staging_frontend_hostname}"

  staging_engine_image = (
    length(trimspace(var.staging_engine_image)) > 0
    ? var.staging_engine_image
    : var.engine_image
  )
}
