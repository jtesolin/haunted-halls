## Description

Prepare the Terraform foundation for a custom-domain frontend mapping while preserving the current deterministic Cloud Run `run.app` authentication model.

## Checklist

- [ ] frontend custom domain variable added
- [ ] hostname validation present
- [ ] Cloud Run domain mapping resource added conditionally
- [ ] `NEXTAUTH_URL` remains on the deterministic Cloud Run URL
- [ ] engine custom domain remains out of scope
- [ ] Google OAuth configuration left unchanged
- [ ] README updated with D6 sequence and verification guidance
- [ ] terraform formatting and validation pass
- [ ] frontend lint/typecheck/test/build pass
