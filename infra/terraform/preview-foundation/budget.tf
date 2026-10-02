data "google_project" "preview" {
  project_id = var.preview_project_id
}

resource "google_billing_budget" "preview" {
  count = var.billing_account_id != "" ? 1 : 0

  billing_account = var.billing_account_id
  display_name    = "haunted-halls-preview-monthly-budget"

  budget_filter {
    projects = ["projects/${data.google_project.preview.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(floor(var.budget_amount))
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }

  depends_on = [google_project_service.apis]
}
