# Preview lifecycle smoke test

Disposable PR for verifying the manual frontend preview deployment lifecycle after issue #82.

This documentation-only change intentionally does not alter application code, infrastructure, or workflows.

Validation checklist:
- [ ] Frontend CI passes without automatic preview deployment
- [ ] Explicit trusted-main dispatch deploys preview for this PR
- [ ] Second dispatch redeploys while preserving the PR database
- [ ] Closing the PR triggers automatic teardown

Do not merge this PR; close it after the test.
