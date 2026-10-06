mock_provider "google" {
  mock_resource "google_secret_manager_secret" {
    override_during = plan
  }
  mock_resource "google_cloud_run_v2_service" {
    override_during = plan
    defaults = {
      uri = "https://private-engine.example.test"
    }
  }
  mock_resource "google_secret_manager_secret_version" {
    override_during = plan
    defaults = {
      version = "7"
    }
  }
}

variables {
  repository_key                = "web"
  pull_request_number           = "123"
  backend_state_prefix          = "previews/web-pr-123"
  preview_project_number        = "123456789012"
  frontend_image                = "us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/frontend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  engine_image                  = "us-east1-docker.pkg.dev/haunted-halls-development/haunted-halls/engine@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  iap_testers                   = ["user:tester@example.com", "group:testers@example.com"]
  secret_revision               = 3
  nextauth_secret               = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  internal_engine_service_token = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
  database_url                  = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
}

run "web_stack" {
  command = plan

  assert {
    condition = (
      output.preview_identity.state_prefix == "previews/web-pr-123" &&
      output.preview_identity.database_name == "haunted_halls_web_pr_123" &&
      google_cloud_run_v2_service.frontend.name == "hh-web-pr-123-frontend" &&
      google_cloud_run_v2_service.engine.name == "hh-web-pr-123-engine" &&
      google_cloud_run_v2_job.migration.name == "hh-web-pr-123-migrate"
    )
    error_message = "All ownership names must derive from the same repository/PR identity."
  }
  assert {
    condition = (
      google_cloud_run_v2_service.frontend.iap_enabled &&
      !google_cloud_run_v2_service.frontend.invoker_iam_disabled &&
      !google_cloud_run_v2_service.engine.invoker_iam_disabled &&
      google_cloud_run_v2_service_iam_member.engine_frontend.member == "serviceAccount:hh-preview-frontend@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_cloud_run_v2_service_iam_member.engine_frontend.name == google_cloud_run_v2_service.engine.name &&
      google_cloud_run_v2_service_iam_member.frontend_iap.member == "serviceAccount:service-123456789012@gcp-sa-iap.iam.gserviceaccount.com" &&
      google_cloud_run_v2_service_iam_member.frontend_iap.name == google_cloud_run_v2_service.frontend.name &&
      alltrue([for binding in google_iap_web_cloud_run_service_iam_member.tester :
        binding.cloud_run_service_name == google_cloud_run_v2_service.frontend.name &&
        binding.role == "roles/iap.httpsResourceAccessor"
      ])
    )
    error_message = "Invoker and tester grants must stay on the exact preview services."
  }
  assert {
    condition = (
      google_cloud_run_v2_service.frontend.template[0].service_account == "hh-preview-frontend@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_cloud_run_v2_service.engine.template[0].service_account == "hh-preview-engine@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_cloud_run_v2_job.migration.template[0].template[0].service_account == "hh-preview-migration@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_cloud_run_v2_job.migration.template[0].template[0].volumes[0].cloud_sql_instance[0].instances == tolist(["haunted-halls-development:us-east1:haunted-halls-postgres"]) &&
      length(google_cloud_run_v2_service.frontend.template[0].volumes) == 0
    )
    error_message = "Reuse accepted runtimes/SQL attachment without granting frontend DB connectivity."
  }
  assert {
    condition = (
      google_cloud_run_v2_job.migration.template[0].template[0].containers[0].image == var.engine_image &&
      google_cloud_run_v2_service.engine.template[0].containers[0].image == var.engine_image &&
      google_cloud_run_v2_service.frontend.template[0].containers[0].image == var.frontend_image &&
      google_cloud_run_v2_job.migration.template[0].template[0].containers[0].command == tolist(["alembic"]) &&
      google_cloud_run_v2_job.migration.template[0].template[0].containers[0].args == tolist(["upgrade", "head"]) &&
      google_cloud_run_v2_job.migration.template[0].template[0].max_retries == 0 &&
      google_cloud_run_v2_job.migration.template[0].task_count == 1 &&
      google_cloud_run_v2_job.migration.template[0].parallelism == 1
    )
    error_message = "Migration must be an explicit single-task Alembic job on the frozen engine digest."
  }
  assert {
    condition = alltrue([for service in [google_cloud_run_v2_service.frontend, google_cloud_run_v2_service.engine] :
      service.project == "hh-preview-458395246135" &&
      service.location == "us-east1" &&
      service.template[0].scaling[0].min_instance_count == 0 &&
      service.template[0].scaling[0].max_instance_count == 2 &&
      service.template[0].containers[0].resources[0].limits == tomap({ cpu = "1", memory = "512Mi" }) &&
      service.template[0].containers[0].resources[0].cpu_idle &&
      !service.deletion_protection
    ])
    error_message = "Previews must be bounded, scale to zero, and removable."
  }
  assert {
    condition = (
      tomap({ for env in google_cloud_run_v2_service.frontend.template[0].containers[0].env : env.name => env.value if length(env.value_source) == 0 }) == tomap({
        AUTH_MODE                = "iap"
        IAP_EXPECTED_AUDIENCE    = "/projects/123456789012/locations/us-east1/services/hh-web-pr-123-frontend"
        NEXTAUTH_URL             = "https://hh-web-pr-123-frontend-123456789012.us-east1.run.app"
        ENGINE_BASE_URL          = "https://private-engine.example.test"
        ENGINE_ID_TOKEN_AUDIENCE = "https://private-engine.example.test"
      })
    )
    error_message = "Frontend must use only server-side IAP config and the matching private engine URL/audience."
  }
  assert {
    condition = (
      length(google_secret_manager_secret.pr) == 3 &&
      length(google_secret_manager_secret_iam_member.runtime) == 5 &&
      google_secret_manager_secret_iam_member.runtime["frontend_nextauth"].member == "serviceAccount:hh-preview-frontend@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_secret_manager_secret_iam_member.runtime["migrate_database"].member == "serviceAccount:hh-preview-migration@hh-preview-458395246135.iam.gserviceaccount.com" &&
      google_secret_manager_secret_version.database_url.secret_data_wo_version == 3 &&
      google_secret_manager_secret_version.nextauth.deletion_policy == "ABANDON"
    )
    error_message = "Only three disposable secrets and five minimal runtime secret grants are allowed."
  }
  assert {
    condition = (
      { for env in google_cloud_run_v2_service.frontend.template[0].containers[0].env : env.name => env.value_source[0].secret_key_ref[0].secret if length(env.value_source) > 0 } == {
        NEXTAUTH_SECRET               = google_secret_manager_secret.pr["nextauth"].id
        INTERNAL_ENGINE_SERVICE_TOKEN = google_secret_manager_secret.pr["internal_token"].id
      } &&
      { for env in google_cloud_run_v2_service.engine.template[0].containers[0].env : env.name => env.value_source[0].secret_key_ref[0].secret if length(env.value_source) > 0 } == {
        DATABASE_URL                  = google_secret_manager_secret.pr["database_url"].id
        INTERNAL_ENGINE_SERVICE_TOKEN = google_secret_manager_secret.pr["internal_token"].id
        OPENAI_API_KEY                = "projects/hh-preview-458395246135/secrets/hh-preview-openai-api-key"
      } &&
      one(google_cloud_run_v2_job.migration.template[0].template[0].containers[0].env).value_source[0].secret_key_ref[0].secret == google_secret_manager_secret.pr["database_url"].id &&
      one(google_cloud_run_v2_job.migration.template[0].template[0].containers[0].env).value_source[0].secret_key_ref[0].version == "7" &&
      alltrue([for env in google_cloud_run_v2_service.engine.template[0].containers[0].env :
        env.value_source[0].secret_key_ref[0].version == (env.name == "OPENAI_API_KEY" ? "1" : "7") if length(env.value_source) > 0
      ])
    )
    error_message = "Secrets must be minimal, preview-only, and pinned to actual created versions, not the write-only rotation trigger."
  }
}

run "bounded_engine_namespace" {
  command = plan
  variables {
    repository_key       = "engine"
    pull_request_number  = "999999999"
    backend_state_prefix = "previews/engine-pr-999999999"
    database_url         = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_engine_pr_999999999?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }

  assert {
    condition = (
      output.preview_identity.database_name == "haunted_halls_engine_pr_999999999" &&
      output.preview_identity.frontend_name == "hh-engine-pr-999999999-frontend" &&
      output.preview_identity.state_prefix == "previews/engine-pr-999999999" &&
      length(output.preview_identity.frontend_name) <= 49 &&
      length(output.preview_identity.engine_name) <= 49 &&
      length(output.preview_identity.migration_name) <= 49 &&
      length(output.preview_identity.database_name) <= 63 &&
      alltrue([for secret in google_secret_manager_secret.pr : length(secret.secret_id) <= 255])
    )
    error_message = "Repository namespaces must not collide, including at the maximum accepted PR number."
  }
}

run "migration_prerequisites_only" {
  command = plan
  plan_options {
    target = [google_cloud_run_v2_job.migration]
  }
  assert {
    condition = (
      google_cloud_run_v2_job.migration.template[0].template[0].containers[0].image == var.engine_image &&
      google_secret_manager_secret_version.database_url.secret_data_wo_version == var.secret_revision &&
      google_secret_manager_secret_version.internal_token.secret_data_wo_version == var.secret_revision &&
      google_secret_manager_secret_version.nextauth.secret_data_wo_version == var.secret_revision &&
      length(google_secret_manager_secret_iam_member.runtime) == 5
    )
    error_message = "Targeting migration must prepare all PR secrets and minimal runtime IAM before explicit execution."
  }
}

run "reject_leading_zero" {
  command = plan
  variables {
    pull_request_number  = "0123"
    backend_state_prefix = "previews/web-pr-0123"
    database_url         = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_0123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.pull_request_number]
}

run "reject_wrong_state" {
  command = plan
  variables {
    backend_state_prefix = "previews/web-pr-124"
  }
  expect_failures = [var.backend_state_prefix]
}

run "reject_frontend_tag" {
  command = plan
  variables {
    frontend_image = "us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/frontend:latest"
  }
  expect_failures = [var.frontend_image]
}

run "reject_wrong_engine_repository" {
  command = plan
  variables {
    engine_image = "us-east1-docker.pkg.dev/hh-preview-458395246135/haunted-halls-preview/engine@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  expect_failures = [var.engine_image]
}

run "reject_public_testers" {
  command = plan
  variables {
    iap_testers = ["allUsers"]
  }
  expect_failures = [var.iap_testers]
}

run "reject_production_database" {
  command = plan
  variables {
    database_url = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.database_url]
}

run "reject_weak_token" {
  command = plan
  variables {
    internal_engine_service_token = "placeholder"
  }
  expect_failures = [var.internal_engine_service_token]
}

run "reject_aliased_openai_version" {
  command = plan
  variables {
    preview_openai_version = "latest"
  }
  expect_failures = [var.preview_openai_version]
}

run "reject_unknown_repository" {
  command = plan
  variables {
    repository_key       = "frontend"
    backend_state_prefix = "previews/frontend-pr-123"
    database_url         = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_frontend_pr_123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.repository_key]
}

run "reject_zero_pr" {
  command = plan
  variables {
    pull_request_number  = "0"
    backend_state_prefix = "previews/web-pr-0"
    database_url         = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_0?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.pull_request_number]
}

run "reject_unbounded_pr" {
  command = plan
  variables {
    pull_request_number  = "1000000000"
    backend_state_prefix = "previews/web-pr-1000000000"
    database_url         = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_1000000000?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.pull_request_number]
}

run "reject_wrong_project_frontend" {
  command = plan
  variables {
    frontend_image = "us-east1-docker.pkg.dev/haunted-halls-development/haunted-halls/frontend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  expect_failures = [var.frontend_image]
}

run "reject_uppercase_engine_digest" {
  command = plan
  variables {
    engine_image = "us-east1-docker.pkg.dev/haunted-halls-development/haunted-halls/engine@sha256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
  }
  expect_failures = [var.engine_image]
}

run "reject_empty_testers" {
  command = plan
  variables {
    iap_testers = []
  }
  expect_failures = [var.iap_testers]
}

run "reject_other_pr_database" {
  command = plan
  variables {
    database_url = "postgresql+psycopg://haunted_halls_preview_app:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_124?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.database_url]
}

run "reject_admin_database_login" {
  command = plan
  variables {
    database_url = "postgresql+psycopg://postgres:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee@/haunted_halls_web_pr_123?host=/cloudsql/haunted-halls-development:us-east1:haunted-halls-postgres"
  }
  expect_failures = [var.database_url]
}

run "reject_weak_nextauth_secret" {
  command = plan
  variables {
    nextauth_secret = "placeholder"
  }
  expect_failures = [var.nextauth_secret]
}

run "reject_fractional_secret_revision" {
  command = plan
  variables {
    secret_revision = 1.5
  }
  expect_failures = [var.secret_revision]
}
