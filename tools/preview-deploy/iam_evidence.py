"""Value-free IAM evidence; never serialize policy contents or exceptions."""

import json
import re
from datetime import datetime, timezone


def cli_error_kind(diagnostic, resource):
    lowered = diagnostic.lower()
    # Hyphens, paths and colons can embed numbers in resource identifiers.
    denied_status = re.search(
        rb"(?<![\w./:-])(?:401|403)(?![\w./:-])", lowered,
    ) or re.search(
        rb"""(?<![\w./:-])(?:code|status(?:_code)?)["']?\s*[:=]\s*["']?(?:401|403)(?![\w./:-])""",
        lowered,
    )
    if denied_status or any(marker in lowered for marker in (
        b"unauthenticated", b"permission_denied", b"permission denied",
    )):
        return "permission_denied"
    if (b"not_found" in lowered or b"not found" in lowered) and resource.encode() in diagnostic:
        return "not_found"
    return "cli_read_failed"


def shape(value):
    fields = {}
    if isinstance(value, dict):
        for key in ("bindings", "etag", "version"):
            item = value.get(key)
            fields[key] = {"present": key in value, "type": type(item).__name__}
            if isinstance(item, list):
                fields[key]["count"] = len(item)
        fields["other_field_count"] = len(set(value) - {"bindings", "etag", "version"})
    return {"type": type(value).__name__, "fields": fields}


def condition(policy, role):
    """Describe the existing verifier's first rejected condition, without relaxing it."""
    if not isinstance(policy, dict):
        return "policy_not_object"
    bindings = policy.get("bindings")
    if set(policy) == {"etag"} and isinstance(policy["etag"], str) and policy["etag"]:
        bindings = []
    if not isinstance(bindings, list):
        if set(policy) == {"etag"}:
            return "etag_not_nonempty_string"
        return "bindings_missing" if "bindings" not in policy else "bindings_not_list"
    for binding in bindings:
        if (not isinstance(binding, dict) or not isinstance(binding.get("role"), str)
                or not isinstance(binding.get("members", []), list)):
            return "binding_structure_invalid"
        if binding["role"] == role:
            if not all(isinstance(member, str) for member in binding.get("members", [])):
                return "owned_member_not_string"
            if binding.get("condition"):
                return "owned_binding_conditional"
    if any(b["role"] == role and b.get("members") for b in bindings):
        return "owned_members_remain"
    return "empty_owned_role"


def body_shape(body):
    if body is None:
        return {"type": "unavailable", "condition": "body_read_failed"}
    if not body.strip():
        return {"type": "unavailable", "condition": "empty_body"}
    try:
        return shape(json.loads(body))
    except (ValueError, UnicodeError):
        return {"type": "unavailable", "condition": "invalid_json"}


def record(resource_type, resource, operation, endpoint, parent_state, policy=None,
           http_status=None, cli_exit_code=None, validation_condition="unavailable"):
    return {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "resource_type": resource_type, "resource": resource,
        "operation": operation, "endpoint": endpoint,
        "http_status": http_status, "cli_exit_code": cli_exit_code,
        "parent_state": parent_state, "sanitized_json_shape": shape(policy),
        "validation_condition": validation_condition,
    }


def emit(evidence):
    print("IAM verification: " + json.dumps(evidence, sort_keys=True))
