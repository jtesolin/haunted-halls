import re
from collections.abc import Mapping, Sequence


PROTECTED_DATABASES = frozenset({"haunted_halls", "haunted_halls_staging"})
REPOSITORY_KEYS = frozenset({"web", "engine"})
MAX_PULL_REQUEST_NUMBER = 999_999_999
_ALLOWED_DATABASE_NAME = re.compile(r"^haunted_halls_(?:web|engine)_pr_[1-9][0-9]{0,8}$")


class InvalidProvisioningRequest(ValueError):
    pass


def validate_role_memberships(
    memberships: Mapping[str, Sequence[Mapping[str, object]]],
) -> None:
    if set(memberships) != {
        "haunted_halls_preview_app",
        "haunted_halls_preview_provisioner",
    }:
        raise ValueError("preview database role memberships are not hardened")
    if memberships["haunted_halls_preview_app"] != []:
        raise ValueError("preview database role memberships are not hardened")

    provisioner_memberships = memberships["haunted_halls_preview_provisioner"]
    if len(provisioner_memberships) != 1:
        raise ValueError("preview database role memberships are not hardened")

    membership = provisioner_memberships[0]
    if not isinstance(membership, Mapping):
        raise ValueError("preview database role memberships are not hardened")
    if (
        membership.get("granted_role_name") != "haunted_halls_preview_app"
        or type(membership.get("admin_option")) is not bool
        or membership["admin_option"] is not False
        or type(membership.get("inherit_option")) is not bool
        or membership["inherit_option"] is not False
        or type(membership.get("set_option")) is not bool
        or membership["set_option"] is not True
        or set(membership)
        != {
            "granted_role_name",
            "admin_option",
            "inherit_option",
            "set_option",
        }
    ):
        raise ValueError("preview database role memberships are not hardened")


def validate_provisioner_search_path(search_path: object, role_config: object) -> None:
    configured_paths = (
        [
            setting.partition("=")[2]
            for setting in role_config
            if isinstance(setting, str) and setting.startswith("search_path=")
        ]
        if isinstance(role_config, (list, tuple))
        else []
    )
    if search_path != "pg_catalog" or configured_paths != ["pg_catalog"]:
        raise ValueError("preview provisioner search_path is not hardened")


def validate_preview_role_attributes(
    roles: Mapping[str, Mapping[str, object]],
) -> None:
    expected_roles = {
        "haunted_halls_preview_app",
        "haunted_halls_preview_provisioner",
    }
    if set(roles) != expected_roles:
        raise ValueError("preview database roles are incomplete")

    if any(
        role.get(attribute) is not False
        for role in roles.values()
        for attribute in ("rolinherit", "rolreplication", "rolbypassrls")
    ):
        raise ValueError("preview database role attributes are not hardened")


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
