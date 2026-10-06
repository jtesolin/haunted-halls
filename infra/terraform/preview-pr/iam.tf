resource "google_cloud_run_v2_service_iam_member" "engine_frontend" {
  project  = local.project_id
  location = local.region
  name     = google_cloud_run_v2_service.engine.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.frontend_runtime}"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_iap" {
  project  = local.project_id
  location = local.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.iap_service_agent}"
}

resource "google_iap_web_cloud_run_service_iam_member" "tester" {
  for_each               = var.iap_testers
  project                = local.project_id
  location               = local.region
  cloud_run_service_name = google_cloud_run_v2_service.frontend.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value

  depends_on = [google_cloud_run_v2_service_iam_member.frontend_iap]
}
