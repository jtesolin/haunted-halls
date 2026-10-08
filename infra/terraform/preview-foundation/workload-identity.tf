locals {
  frontend_workflow_ref           = "jtesolin/haunted-halls/.github/workflows/preview-deploy.yml@refs/heads/main"
  engine_workflow_ref             = "jtesolin/haunted-halls-engine/.github/workflows/preview-deploy.yml@refs/heads/main"
  secret_preparation_workflow_ref = "jtesolin/haunted-halls/.github/workflows/preview-secret-prepare.yml@refs/heads/main"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "hh-preview-github"
  display_name              = "Haunted Halls preview GitHub"
  description               = "Only the reviewed default-branch preview deployment workflow files may federate."

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-preview"
  display_name                       = "Haunted Halls preview OIDC"
  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
    "attribute.workflow_ref"     = "assertion.workflow_ref"
  }

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_condition = "attribute.repository_owner == \"jtesolin\" && attribute.ref == \"refs/heads/main\" && attribute.workflow_ref in [\"${local.frontend_workflow_ref}\", \"${local.engine_workflow_ref}\", \"${local.secret_preparation_workflow_ref}\"]"
}

resource "google_service_account_iam_member" "frontend_workflow" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.workflow_ref/${local.frontend_workflow_ref}"
}

resource "google_service_account_iam_member" "engine_workflow" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.workflow_ref/${local.engine_workflow_ref}"
}

resource "google_service_account_iam_member" "secret_preparation_workflow" {
  service_account_id = google_service_account.secret_preparer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.workflow_ref/${local.secret_preparation_workflow_ref}"
}

output "preview_workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}
