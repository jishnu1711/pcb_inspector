from __future__ import annotations

import argparse
import json

from device.app import run_local_job


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local UNO Q PCB inspector dry run")
    parser.add_argument("job_manifest", help="Path to the JSON job input manifest")
    args = parser.parse_args()
    print(json.dumps(run_local_job(args.job_manifest), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
