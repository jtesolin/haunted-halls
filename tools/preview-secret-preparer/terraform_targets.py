"""Reviewed, fixed Terraform target inventory for the two narrow 41C phases."""

import argparse
import json

TARGETS = {
    "containers": (
        "google_secret_manager_secret.pr",
        "google_secret_manager_secret_iam_member.runtime",
    ),
    "migration": ("google_cloud_run_v2_job.migration",),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=tuple(TARGETS))
    args = parser.parse_args()
    print(json.dumps([f"-target={address}" for address in TARGETS[args.phase]]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
