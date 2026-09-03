## Summary

Adds the D6A custom-domain foundation for the public frontend Cloud Run service, without altering the deterministic run.app authentication URL model or the private engine URL model.

## Changes

- Adds optional `frontend_custom_domain` Terraform variable with safe hostname validation
- Adds a conditional `google_cloud_run_domain_mapping` resource for the frontend
- Keeps `NEXTAUTH_URL` pointed at the deterministic Cloud Run frontend URL during the foundation phase
- Leaves the engine URL and OAuth configuration unchanged
- Documents the domain verification and DNS manual-record flow in the README
- Adds the example tfvars entry for the optional custom domain

## Scope / Non-goals

- No Terraform apply
- No DNS changes
- No Google OAuth client changes
- No `NEXTAUTH_URL` cutover
- No engine custom domain
- No deployment or workflow execution
