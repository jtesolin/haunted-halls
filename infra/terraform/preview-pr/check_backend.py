"""Offline identity/backend guard; never initializes or contacts a backend."""

import argparse
import json
import re
import sys
from pathlib import Path


BUCKET = "hh-preview-458395246135-per-pr-tf-state"
DEPLOYER = "hh-preview-deployer@hh-preview-458395246135.iam.gserviceaccount.com"


def state_prefix(repository_key: str, pr_number: str) -> str:
    if repository_key not in {"web", "engine"}:
        raise ValueError("repository key must be exactly web or engine")
    if not re.fullmatch(r"[1-9][0-9]{0,8}", pr_number):
        raise ValueError("PR number must be canonical decimal in 1..999999999")
    return f"previews/{repository_key}-pr-{pr_number}"


def verify_backend(metadata: object, repository_key: str, pr_number: str) -> None:
    prefix = state_prefix(repository_key, pr_number)
    if not isinstance(metadata, dict):
        raise ValueError("invalid Terraform backend metadata")
    backend = metadata.get("backend")
    if not isinstance(backend, dict) or backend.get("type") != "gcs":
        raise ValueError("expected initialized GCS backend")
    config = backend.get("config")
    if not isinstance(config, dict) or any(
        config.get(key) != value
        for key, value in {
            "bucket": BUCKET,
            "prefix": prefix,
            "impersonate_service_account": DEPLOYER,
        }.items()
    ):
        raise ValueError("backend bucket, prefix, or deployer differs from preview identity")
    if config.get("impersonate_service_account_delegates"):
        raise ValueError("backend impersonation delegates are not allowed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository_key")
    parser.add_argument("pr_number")
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify_backend(
            json.loads(args.metadata.read_text()),
            args.repository_key,
            args.pr_number,
        )
    except json.JSONDecodeError:
        print("ERROR: backend metadata is not valid JSON", file=sys.stderr)
        return 1
    except OSError:
        print("ERROR: backend metadata cannot be read", file=sys.stderr)
        return 1
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Preview backend identity verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
