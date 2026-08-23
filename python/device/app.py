from __future__ import annotations

from .config import JobInput
from .job_runner import JobRunner


def run_local_job(manifest_path: str) -> dict:
    return JobRunner().run(JobInput.from_json_file(manifest_path))
