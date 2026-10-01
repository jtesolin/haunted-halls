import re
from collections.abc import Mapping


PROTECTED_DATABASES = frozenset({"haunted_halls", "haunted_halls_staging"})
REPOSITORY_KEYS = frozenset({"web", "engine"})
MAX_PULL_REQUEST_NUMBER = 999_999_999
_ALLOWED_DATABASE_NAME = re.compile(r"^haunted_halls_(?:web|engine)_pr_[1-9][0-9]{0,8}$")


class InvalidProvisioningRequest(ValueError):
    pass


def validate_role_memberships(memberships: Mapping[str, set[str]]) -> None:
    expected_memberships = {
        "haunted_halls_preview_app": set(),
        "haunted_halls_preview_provisioner": {"haunted_halls_preview_app"},
    }
    if memberships != expected_memberships:
        raise ValueError("preview database role memberships are not hardened")


def validate_database_name(database_name: object) -> str:
    if not isinstance(database_name, str):
        raise InvalidProvisioningRequest("database name must be a string")
    if database_name in PROTECTED_DATABASES:
        raise InvalidProvisioningRequest("protected database names are not allowed")
    if not _ALLOWED_DATABASE_NAME.fullmatch(database_name):
        raise InvalidProvisioningRequest("database name is not an allowed preview name")
    return database_name


def derive_database_name(repository_key: object, pull_request_number: object) -> str:
    if not isinstance(repository_key, str) or repository_key not in REPOSITORY_KEYS:
        raise InvalidProvisioningRequest("repository_key must be web or engine")
    if type(pull_request_number) is not int:
        raise InvalidProvisioningRequest("pull_request_number must be an integer")
    if not 1 <= pull_request_number <= MAX_PULL_REQUEST_NUMBER:
        raise InvalidProvisioningRequest("pull_request_number is outside the allowed range")

    return validate_database_name(
        f"haunted_halls_{repository_key}_pr_{pull_request_number}"
    )


def validate_request(request: object) -> tuple[str, str]:
    if not isinstance(request, dict) or set(request) != {
        "operation",
        "repository_key",
        "pull_request_number",
    }:
        raise InvalidProvisioningRequest(
            "request must contain only operation, repository_key, and pull_request_number"
        )

    operation = request["operation"]
    if not isinstance(operation, str) or operation not in {"create", "drop"}:
        raise InvalidProvisioningRequest("operation must be create or drop")

    database_name = derive_database_name(
        request["repository_key"], request["pull_request_number"]
    )
    return operation, database_name
