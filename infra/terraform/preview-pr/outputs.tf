output "preview_identity" {
  value = {
    project_id     = local.project_id
    repository_key = var.repository_key
    pr_number      = var.pull_request_number
    state_bucket   = "hh-preview-458395246135-per-pr-tf-state"
    state_prefix   = var.backend_state_prefix
    database_name  = local.database_name
    frontend_name  = local.frontend_name
    engine_name    = local.engine_name
    migration_name = local.migration_name
    frontend_url   = local.frontend_url
    engine_url     = google_cloud_run_v2_service.engine.uri
    frontend_image = var.frontend_image
    engine_image   = var.engine_image
    iap_audience   = local.iap_audience
  }
}
