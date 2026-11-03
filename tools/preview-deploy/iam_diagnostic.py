#!/usr/bin/env python3
"""Explicit closed-PR IAM reads only; no lifecycle instance or cleanup entry point."""

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

from teardown import LifecycleError, PreviewTeardown
from iam_evidence import condition as policy_condition, record, shape


WORKFLOW = "jtesolin/haunted-halls/.github/workflows/preview-deploy.yml@refs/heads/main"
DEPLOYER = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"
PROJECT = "hh-preview-458395246135"
REGION = "us-east1"
SERVICES = ("hh-web-pr-76-engine", "hh-web-pr-76-frontend")
RUN_ROOT = f"https://{REGION}-run.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/services/"
RUN_POLICY_SUFFIX = ":getIamPolicy?options.requestedPolicyVersion=3"
IAP_RESOURCE = "projects/1001419903197/iap_web/cloud_run-us-east1/services/hh-web-pr-76-frontend"
IAP_URL = f"https://iap.googleapis.com/v1/{IAP_RESOURCE}:getIamPolicy?options.requestedPolicyVersion=3"
IMPERSONATE = False


def canonical_number(number):
    if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,8}", number):
        raise LifecycleError("Diagnostic PR number must be a canonical positive integer.")
    return number


def configure_targets(number):
    number = canonical_number(number)
    global SERVICES, IAP_RESOURCE, IAP_URL
    SERVICES = (f"hh-web-pr-{number}-engine", f"hh-web-pr-{number}-frontend")
    IAP_RESOURCE = f"projects/1001419903197/iap_web/cloud_run-us-east1/services/hh-web-pr-{number}-frontend"
    IAP_URL = f"https://iap.googleapis.com/v1/{IAP_RESOURCE}:getIamPolicy?options.requestedPolicyVersion=3"


def validate_closed_pr(number):
    canonical_number(number)
    # Public fixed-repository metadata needs no new GitHub token or job permission.
    request = urllib.request.Request(
        f"https://api.github.com/repos/jtesolin/haunted-halls/pulls/{number}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "haunted-halls-iam-diagnostic"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            if response.status != 200:
                raise LifecycleError("Closed PR metadata unavailable; diagnostic not executed.")
            pr = json.load(response)
    except (urllib.error.URLError, OSError):
        raise LifecycleError("Closed PR metadata unavailable; diagnostic not executed.") from None
    except (ValueError, UnicodeError):
        raise LifecycleError("Closed PR metadata invalid; diagnostic not executed.") from None
    if not (
        isinstance(pr, dict) and type(pr.get("number")) is int and str(pr["number"]) == number
        and pr.get("state") == "closed" and isinstance(pr.get("closed_at"), str)
        and pr["closed_at"] and isinstance(pr.get("base"), dict)
        and pr["base"].get("ref") == "main" and isinstance(pr["base"].get("repo"), dict)
        and pr["base"]["repo"].get("full_name") == "jtesolin/haunted-halls"
    ):
        raise LifecycleError("Diagnostic requires a closed frontend PR targeting main.")


def impersonation_args():
    return [f"--impersonate-service-account={DEPLOYER}"] if IMPERSONATE else []


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
        raise LifecycleError("Actions diagnostic requires explicit iam-diagnostic operation and PR 76.")
    return canonical_number(inputs["pull_request_number"])


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


def api_condition(status, policy, error, parent_absent, role):
    if status == 200:
        return "invalid_json" if error else policy_condition(policy, role)
    if status == 404:
        return "not_found_with_absent_parent" if parent_absent else "parent_absence_unverified"
    if status in (401, 403):
        return "permission_denied"
    return "transport_unavailable" if status is None else "http_read_failed"


def cli_policy(name):
    if name not in SERVICES:
        raise LifecycleError("Diagnostic CLI target is not the validated PR.")
    try:
        result = subprocess.run(
            ["gcloud", "run", "services", "get-iam-policy", name,
             f"--project={PROJECT}", f"--region={REGION}", "--format=json", *impersonation_args()],
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
        denied = b"PERMISSION_DENIED" in diagnostic or b"403" in diagnostic or b"401" in diagnostic
        return result.returncode, None, missing, (
            "Cloud Run CLI permission denied." if denied else "Cloud Run CLI policy read failed."
        )
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
            **record("cloud_run_service",
                     f"projects/{PROJECT}/locations/{REGION}/services/{name}",
                     "GET getIamPolicy", RUN_ROOT + name + RUN_POLICY_SUFFIX,
                     "absent" if parent_status == 404 else "exists" if parent_status == 200 else "unknown",
                     policy, http_status=status, cli_exit_code=code,
                     validation_condition=api_condition(
                         status, policy, error, absent[name], "roles/run.invoker")),
            "api_method": "GET Cloud Run v1 getIamPolicy",
            "parent_http_status": parent_status,
            "result": combined, "api_verifier": result, "condition": condition,
            "cli_sanitized_json_shape": shape(rendered),
            "cli_verifier": cli_result, "cli_condition": cli_condition,
            "cli_validation_condition": (
                "not_found_with_absent_parent" if code and missing and absent[name] else
                "permission_denied" if code and cli_error == "Cloud Run CLI permission denied." else
                "cli_read_failed" if code else "invalid_json" if cli_error else
                policy_condition(rendered, "roles/run.invoker")
            ),
            "classification": "malformed-or-binding-present" if combined == "FAIL"
            else "inaccessible-or-unverified" if combined == "INCONCLUSIVE"
            else "empty-owned-role-with-absent-parent",
        })
    status, policy, error = read_policy(IAP_URL, "POST", token)
    result, condition = validate(
        status, policy, error, absent[SERVICES[1]], "roles/iap.httpsResourceAccessor")
    records.append({
        **record("iap_web_service", IAP_RESOURCE, "POST getIamPolicy", IAP_URL,
                 "absent" if absent[SERVICES[1]] else
                 records[1]["parent_state"], policy, http_status=status,
                 validation_condition=api_condition(
                     status, policy, error, absent[SERVICES[1]], "roles/iap.httpsResourceAccessor")),
        "api_method": "POST IAP getIamPolicy (read-only)",
        "result": result, "condition": condition,
        "classification": "absent" if status == 404 and absent[SERVICES[1]]
        else "empty-owned-role" if result == "PASS" else "malformed-or-inaccessible",
    })
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-context", action="store_true")
    parser.add_argument("--local", action="store_true", help="Explicit local read-only diagnostic for a validated closed PR.")
    parser.add_argument("--pull-request-number")
    parser.add_argument("--impersonate-deployer", action="store_true",
                        help="Use existing impersonation permission only; never changes IAM.")
    args = parser.parse_args()
    try:
        global IMPERSONATE
        IMPERSONATE = False
        if args.local:
            if args.check_context or os.environ.get("GITHUB_ACTIONS") == "true":
                raise LifecycleError("Local diagnostic cannot bypass Actions context validation.")
            number = canonical_number(args.pull_request_number)
        else:
            if args.pull_request_number is not None or args.impersonate_deployer:
                raise LifecycleError("Explicit local arguments require --local.")
            number = check_context()
        if args.check_context:
            return 0
        validate_closed_pr(number)
        configure_targets(number)
        IMPERSONATE = args.impersonate_deployer
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token", *impersonation_args()],
            capture_output=True, timeout=60, check=False,
        )
        if result.returncode or not result.stdout.strip():
            denied = b"PERMISSION_DENIED" in result.stderr or b"403" in result.stderr
            print(json.dumps({
                "result": "INCONCLUSIVE", "pull_request_number": number,
                "identity": DEPLOYER if IMPERSONATE or not args.local else "authenticated-local-operator",
                "cli_exit_code": result.returncode,
                "condition": "permission_denied" if denied else "token_unavailable",
                "policies_queried": 0,
            }))
            return 1
        token = result.stdout.decode("utf-8").strip()
        records = diagnose(token)
        del token
        overall = (
            "FAIL" if any(r["result"] == "FAIL" for r in records)
            else "INCONCLUSIVE" if any(r["result"] != "PASS" for r in records) else "PASS"
        )
        report = {
            "operation": "iam-diagnostic", "pull_request_number": number,
            "identity": DEPLOYER if IMPERSONATE or not args.local else "authenticated-local-operator",
            "configured_deployer": DEPLOYER, "workflow_ref": None if args.local else WORKFLOW,
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
                summary.write(f"## PR {number} read-only IAM diagnostic: {overall}\n\n```json\n{text}\n```\n")
        return 0 if overall == "PASS" else 1
    except (LifecycleError, subprocess.TimeoutExpired, OSError, UnicodeError) as failure:
        # Never serialize subprocess output, HTTP exceptions or credential file paths.
        message = str(failure) if isinstance(failure, LifecycleError) else "Diagnostic unavailable; no cleanup attempted."
        print(json.dumps({"result": "INCONCLUSIVE", "condition": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
