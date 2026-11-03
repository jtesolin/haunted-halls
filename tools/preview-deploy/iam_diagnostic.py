#!/usr/bin/env python3
"""Temporary PR 76 IAM reads only; no lifecycle instance or cleanup entry point."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

from teardown import LifecycleError, PreviewTeardown


WORKFLOW = "jtesolin/haunted-halls/.github/workflows/preview-deploy.yml@refs/heads/main"
DEPLOYER = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"
PROJECT = "hh-preview-458395246135"
REGION = "us-east1"
SERVICES = ("hh-web-pr-76-engine", "hh-web-pr-76-frontend")
RUN_ROOT = f"https://{REGION}-run.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/services/"
RUN_POLICY_SUFFIX = ":getIamPolicy?options.requestedPolicyVersion=3"
IAP_RESOURCE = "projects/1001419903197/iap_web/cloud_run-us-east1/services/hh-web-pr-76-frontend"
IAP_URL = f"https://iap.googleapis.com/v1/{IAP_RESOURCE}:getIamPolicy?options.requestedPolicyVersion=3"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_context():
    if not (
        os.environ.get("GITHUB_WORKFLOW_REF") == WORKFLOW
        and os.environ.get("GITHUB_REPOSITORY") == "jtesolin/haunted-halls"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    ):
        raise LifecycleError("Diagnostic requires the exact trusted main caller and manual event.")
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    except (KeyError, OSError, ValueError):
        raise LifecycleError("Diagnostic event metadata is unavailable.") from None
    repository = event.get("repository") if isinstance(event, dict) else None
    inputs = event.get("inputs") if isinstance(event, dict) else None
    if not (
        isinstance(repository, dict) and isinstance(inputs, dict)
        and repository.get("full_name") == "jtesolin/haunted-halls"
        and inputs.get("operation") == "iam-diagnostic"
        and inputs.get("pull_request_number") == "76"
    ):
        raise LifecycleError("Diagnostic requires explicit iam-diagnostic operation and PR 76.")


def shape(value):
    """Keep only fixed field names, types and counts, never API-provided values."""
    fields = {}
    if isinstance(value, dict):
        for key in ("bindings", "etag", "version"):
            item = value.get(key)
            fields[key] = {"present": key in value, "type": type(item).__name__}
            if isinstance(item, list):
                fields[key]["count"] = len(item)
        fields["other_field_count"] = len(set(value) - {"bindings", "etag", "version"})
    return {"type": type(value).__name__, "fields": fields}


def read_policy(url, method, token):
    # No caller-supplied URL, method, body or headers can reach the network.
    allowed_gets = {RUN_ROOT + name + suffix for name in SERVICES
                    for suffix in ("", RUN_POLICY_SUFFIX)}
    if not ((method == "GET" and url in allowed_gets)
            or (method == "POST" and url == IAP_URL)):
        raise LifecycleError("Diagnostic API target or method is not read-only allowlisted.")
    request = urllib.request.Request(
        url, method=method,
        data=b'{"options":{"requestedPolicyVersion":3}}' if method == "POST" else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            status, body = response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            status, body = error.code, error.read()
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, None, "Transport failed; response unavailable."
    try:
        return status, json.loads(body), None
    except (ValueError, UnicodeError):
        return status, None, "Response is not valid JSON."


def validate(status, policy, error, parent_absent, role):
    if status == 404 and parent_absent:
        return "PASS", "HTTP 404 with independently verified runtime parent absence."
    if status != 200:
        return "INCONCLUSIVE", "Policy API inaccessible; no absence inferred."
    if error:
        return "FAIL", error
    try:
        members = PreviewTeardown.policy_members(policy, role)
    except LifecycleError as failure:
        condition = (
            "policy must be an object" if not isinstance(policy, dict)
            else "bindings must be a list or policy must contain only a nonempty string etag"
            if not isinstance(policy.get("bindings"), list)
            else "binding/member structure or owned-role condition must validate"
        )
        return "FAIL", f"{failure} Condition: {condition}."
    if members:
        return "FAIL", "Owned-role members remain; cleanup cannot continue."
    return "PASS", "Existing policy_members verifier accepts no owned-role members."


def cli_policy(name):
    if name not in SERVICES:
        raise LifecycleError("Diagnostic CLI target is not PR 76.")
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "get-iam-policy", name,
             f"--project={PROJECT}", f"--region={REGION}", "--format=json"],
            capture_output=True, timeout=60, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return -1, None, False, "Cloud Run CLI policy read unavailable."
    if result.returncode:
        diagnostic = result.stdout + result.stderr
        missing = (
            (b"NOT_FOUND" in diagnostic or b"not found" in diagnostic.lower())
            and name.encode() in diagnostic
            and b"PERMISSION_DENIED" not in diagnostic and b"403" not in diagnostic
        )
        return result.returncode, None, missing, "Cloud Run CLI policy read failed."
    try:
        return 0, json.loads(result.stdout), False, None
    except (ValueError, UnicodeError):
        return 0, None, False, "Cloud Run CLI returned invalid JSON."


def diagnose(token):
    records = []
    absent = {}
    for name in SERVICES:
        parent_status, _, _ = read_policy(RUN_ROOT + name, "GET", token)
        absent[name] = parent_status == 404
        status, policy, error = read_policy(RUN_ROOT + name + RUN_POLICY_SUFFIX, "GET", token)
        result, condition = validate(status, policy, error, absent[name], "roles/run.invoker")
        code, rendered, missing, cli_error = cli_policy(name)
        if code:
            cli_result, cli_condition = (
                ("PASS", "CLI NOT_FOUND with verified parent absence.")
                if missing and absent[name] else
                ("INCONCLUSIVE", "CLI read unavailable; no absence inferred.")
            )
        else:
            cli_result, cli_condition = validate(
                200, rendered, cli_error, absent[name], "roles/run.invoker")
        if "FAIL" in (result, cli_result):
            combined = "FAIL"
        elif not absent[name] or result != "PASS" or cli_result != "PASS":
            combined = "INCONCLUSIVE"
        else:
            combined = "PASS"
        records.append({
            "resource": f"projects/{PROJECT}/locations/{REGION}/services/{name}",
            "api_method": "GET Cloud Run v1 getIamPolicy",
            "http_status": status, "parent_http_status": parent_status,
            "sanitized_json_shape": shape(policy),
            "result": combined, "api_verifier": result, "condition": condition,
            "cli_exit_code": code, "cli_sanitized_json_shape": shape(rendered),
            "cli_verifier": cli_result, "cli_condition": cli_condition,
            "classification": "malformed-or-binding-present" if combined == "FAIL"
            else "inaccessible-or-unverified" if combined == "INCONCLUSIVE"
            else "empty-owned-role-with-absent-parent",
        })
    status, policy, error = read_policy(IAP_URL, "POST", token)
    result, condition = validate(
        status, policy, error, absent[SERVICES[1]], "roles/iap.httpsResourceAccessor")
    records.append({
        "resource": IAP_RESOURCE, "api_method": "POST IAP getIamPolicy (read-only)",
        "http_status": status, "sanitized_json_shape": shape(policy),
        "result": result, "condition": condition,
        "classification": "absent" if status == 404 and absent[SERVICES[1]]
        else "empty-owned-role" if result == "PASS" else "malformed-or-inaccessible",
    })
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-context", action="store_true")
    args = parser.parse_args()
    try:
        check_context()
        if args.check_context:
            return 0
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, timeout=60, check=False,
        )
        if result.returncode or not result.stdout.strip():
            raise LifecycleError("Deployer access token unavailable; diagnostic not executed.")
        token = result.stdout.decode("utf-8").strip()
        records = diagnose(token)
        del token
        overall = (
            "FAIL" if any(r["result"] == "FAIL" for r in records)
            else "INCONCLUSIVE" if any(r["result"] != "PASS" for r in records) else "PASS"
        )
        report = {
            "operation": "iam-diagnostic", "pull_request_number": "76",
            "configured_deployer": DEPLOYER, "workflow_ref": WORKFLOW,
            "result": overall, "iam_checks_allow_continuation": overall == "PASS",
            "existing_teardown_policy_checks_pass": all(
                r.get("cli_verifier", r["result"]) == "PASS" for r in records
            ) and all(r["parent_http_status"] == 404 for r in records[:2]),
            "scope": "IAM only; not state/ownership verification or cleanup approval.",
            "historical_failure": "Current results cannot identify the original rejected resource or payload.",
            "policies": records,
        }
        text = json.dumps(report, indent=2)
        print(text)
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
                summary.write(f"## PR 76 read-only IAM diagnostic: {overall}\n\n```json\n{text}\n```\n")
        return 0 if overall == "PASS" else 1
    except (LifecycleError, subprocess.TimeoutExpired, OSError, UnicodeError) as failure:
        # Never serialize subprocess output, HTTP exceptions or credential file paths.
        message = str(failure) if isinstance(failure, LifecycleError) else "Diagnostic unavailable; no cleanup attempted."
        print(json.dumps({"result": "INCONCLUSIVE", "condition": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
