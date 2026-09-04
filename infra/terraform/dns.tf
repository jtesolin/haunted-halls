resource "google_dns_managed_zone" "tesolin_us" {
  name        = "tesolin-us"
  dns_name    = "tesolin.us."
  description = "Authoritative DNS zone for tesolin.us."
  visibility  = "public"

  depends_on = [
    google_project_service.cloud_dns,
  ]
}

resource "google_dns_record_set" "google_site_verification" {
  managed_zone = google_dns_managed_zone.tesolin_us.name
  name         = google_dns_managed_zone.tesolin_us.dns_name
  type         = "TXT"
  ttl          = 300
  rrdatas      = ["\"google-site-verification=IsCn8xrobpc-ZM5o2LzVj6QiQ4aQJHSZluO4eA0vllQ\""]
}
