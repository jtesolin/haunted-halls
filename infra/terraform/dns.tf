resource "google_dns_managed_zone" "tesolin_us" {
  project     = var.project_id
  name        = "tesolin-us"
  dns_name    = "tesolin.us."
  description = "Authoritative DNS zone for tesolin.us."
  visibility  = "public"

  depends_on = [
    google_project_service.cloud_dns,
  ]
}
