"""Fail-closed eligibility gate for the exact frontend PR."""

import json
import re
import sys


def validate_pr(number: str, metadata: object) -> bool:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", number) or not isinstance(metadata, dict):
        return False
    base = metadata.get("base")
    repo = base.get("repo") if isinstance(base, dict) else None
    return (
        type(metadata.get("number")) is int
        and metadata["number"] == int(number)
        and metadata.get("state") == "open"
        and metadata.get("draft") is False
        and isinstance(repo, dict)
        and repo.get("full_name") == "jtesolin/haunted-halls"
    )


def main() -> None:
    message = "Expected the exact open, non-draft frontend PR."
    if len(sys.argv) != 3:
        sys.exit(message)
    try:
        with open(sys.argv[2], encoding="utf-8") as source:
            metadata = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        sys.exit(message)
    if not validate_pr(sys.argv[1], metadata):
        sys.exit(message)


if __name__ == "__main__":
    main()
