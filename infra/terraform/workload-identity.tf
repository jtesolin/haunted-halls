resource "google_iam_workload_identity_pool" "github_actions" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions Pool"
  description               = "OIDC federation for GitHub Actions deployments to the Haunted Halls project."

  depends_on = [
    google_project_service.iam,
  ]
}

# D5A: GitHub Actions CD ownership boundaries
# Terraform manages all Cloud Run configuration.
# GitHub Actions CD workflows own only image revisions.
# WIF restricts federation to deploy.yml workflows on main branch only.
locals {
  frontend_repository = "${var.github_owner}/${var.frontend_repo_name}"
  engine_repository   = "${var.github_owner}/${var.engine_repo_name}"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_actions.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  description                        = "GitHub Actions OIDC provider for Haunted Halls deployment identities."
  attribute_mapping = {
    "google.subject"                  = "assertion.sub"
    "attribute.repository"            = "assertion.repository"
    "attribute.repository_owner"      = "assertion.repository_owner"
    "attribute.ref"                   = "assertion.ref"
    "attribute.repository_visibility" = "assertion.repository_visibility"
    "attribute.aud"                   = "assertion.aud"
    "attribute.environment"           = "assertion.environment"
    "attribute.workflow_ref"          = "assertion.workflow_ref"
    "attribute.workflow_sha"          = "assertion.workflow_sha"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_condition = "attribute.repository_owner == \"${var.github_owner}\" && attribute.ref == \"refs/heads/main\" && ((attribute.repository == \"${local.frontend_repository}\" && attribute.workflow_ref == \"${local.frontend_repository}/.github/workflows/deploy.yml@refs/heads/main\") || (attribute.repository == \"${local.engine_repository}\" && attribute.workflow_ref == \"${local.engine_repository}/.github/workflows/deploy.yml@refs/heads/main\"))"
}

resource "google_service_account_iam_member" "frontend_repository_federation" {
  service_account_id = google_service_account.frontend_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions.name}/attribute.repository/${local.frontend_repository}"
}

resource "google_service_account_iam_member" "engine_repository_federation" {
  service_account_id = google_service_account.engine_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_actions.name}/attribute.repository/${local.engine_repository}"
}

output "github_actions_workload_identity_pool_name" {
  value = google_iam_workload_identity_pool.github_actions.name
}

output "github_actions_workload_identity_provider_name" {
  value = google_iam_workload_identity_pool_provider.github.name
}
