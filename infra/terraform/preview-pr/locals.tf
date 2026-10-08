locals {
  project_id           = "hh-preview-458395246135"
  region               = "us-east1"
  resource_prefix      = "hh-${var.repository_key}-pr-${var.pull_request_number}"
  database_name        = "haunted_halls_${var.repository_key}_pr_${var.pull_request_number}"
  secret_prefix        = "${local.resource_prefix}-i-${var.pr_incarnation}"
  frontend_name        = "${local.resource_prefix}-frontend"
  engine_name          = "${local.resource_prefix}-engine"
  migration_name       = "${local.resource_prefix}-migrate"
  frontend_url         = "https://${local.frontend_name}-${var.preview_project_number}.${local.region}.run.app"
  cloud_sql_connection = "haunted-halls-development:us-east1:haunted-halls-postgres"
  frontend_runtime     = "hh-preview-frontend@${local.project_id}.iam.gserviceaccount.com"
  engine_runtime       = "hh-preview-engine@${local.project_id}.iam.gserviceaccount.com"
  migration_runtime    = "hh-preview-migration@${local.project_id}.iam.gserviceaccount.com"
  iap_service_agent    = "service-${var.preview_project_number}@gcp-sa-iap.iam.gserviceaccount.com"
  iap_audience         = "/projects/${var.preview_project_number}/locations/${local.region}/services/${local.frontend_name}"
  labels = {
    app          = "haunted-halls"
    environment  = "preview"
    repository   = var.repository_key
    pull_request = var.pull_request_number
    incarnation  = var.pr_incarnation
    managed_by   = "terraform"
  }
  secret_names = {
    nextauth       = "${local.secret_prefix}-nextauth"
    internal_token = "${local.secret_prefix}-internal-token"
    database_url   = "${local.secret_prefix}-database-url"
  }
  secret_grants = {
    frontend_nextauth = { secret = "nextauth", member = local.frontend_runtime }
    frontend_token    = { secret = "internal_token", member = local.frontend_runtime }
    engine_token      = { secret = "internal_token", member = local.engine_runtime }
    engine_database   = { secret = "database_url", member = local.engine_runtime }
    migrate_database  = { secret = "database_url", member = local.migration_runtime }
  }
}
