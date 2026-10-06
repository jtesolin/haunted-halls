terraform {
  required_version = ">= 1.11.4, < 2.0.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.46"
    }
  }

  backend "gcs" {
    bucket                      = "hh-preview-458395246135-per-pr-tf-state"
    impersonate_service_account = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"
  }
}
