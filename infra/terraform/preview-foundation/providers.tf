provider "google" {
  project               = var.preview_project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.preview_project_id
}

provider "google" {
  alias                 = "existing"
  project               = var.existing_project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.existing_project_id
}

provider "google-beta" {
  project               = var.preview_project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.preview_project_id
}

provider "random" {}
