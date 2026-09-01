output "terraform_state_bucket_name" {
  description = "Name of the remote Terraform state bucket created by bootstrap."
  value       = google_storage_bucket.terraform_state.name
}

output "terraform_state_bucket_url" {
  description = "GCS URI for the Terraform remote state bucket."
  value       = "gs://${google_storage_bucket.terraform_state.name}"
}
