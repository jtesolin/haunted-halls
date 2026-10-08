"""Fail-closed eligibility gate for the exact frontend PR."""

import json
import re
import sys


def validate_pr(number: str, metadata: object, expected_head_sha: str | None = None) -> bool:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", number) or not isinstance(metadata, dict):
        return False
    base = metadata.get("base")
    repo = base.get("repo") if isinstance(base, dict) else None
    head = metadata.get("head")
    head_repo = head.get("repo") if isinstance(head, dict) else None
    valid = (
        type(metadata.get("number")) is int
        and metadata["number"] == int(number)
        and metadata.get("state") == "open"
        and metadata.get("draft") is False
        and isinstance(base, dict)
        and base.get("ref") == "main"
        and isinstance(repo, dict)
        and repo.get("full_name") == "jtesolin/haunted-halls"
        and isinstance(head_repo, dict)
        and head_repo.get("full_name") == "jtesolin/haunted-halls"
    )
    if not valid:
        return False
    return (
        expected_head_sha is None
        or (
            bool(re.fullmatch(r"[0-9a-f]{40}", expected_head_sha))
            and isinstance(head, dict)
            and head.get("sha") == expected_head_sha
            and isinstance(head_repo, dict)
            and head_repo.get("full_name") == "jtesolin/haunted-halls"
        )
    )


def main() -> None:
    message = "Expected the exact open, non-draft frontend PR."
    if len(sys.argv) not in {3, 4}:
        sys.exit(message)
    try:
        with open(sys.argv[2], encoding="utf-8") as source:
            metadata = json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        sys.exit(message)
    expected_head_sha = sys.argv[3] if len(sys.argv) == 4 else None
    if not validate_pr(sys.argv[1], metadata, expected_head_sha):
        sys.exit(message)


if __name__ == "__main__":
    main()
