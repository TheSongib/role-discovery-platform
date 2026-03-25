import csv
import json
from datetime import datetime
from pathlib import Path

from db import get_all_jobs


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_csv(output_path: Path = None, remote_only: bool = False, max_age_days: int = 3) -> Path:
    if output_path is None:
        output_path = Path(f"jobs_export_{_timestamp()}.csv")

    jobs = get_all_jobs(remote_only=remote_only, max_age_days=max_age_days)
    if not jobs:
        print("No jobs to export.")
        return output_path

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=jobs[0].keys())
        writer.writeheader()
        writer.writerows(dict(job) for job in jobs)

    print(f"Exported {len(jobs)} jobs → {output_path}")
    return output_path


def export_json(output_path: Path = None, remote_only: bool = False, max_age_days: int = 3) -> Path:
    if output_path is None:
        output_path = Path(f"jobs_export_{_timestamp()}.json")

    jobs = get_all_jobs(remote_only=remote_only, max_age_days=max_age_days)
    if not jobs:
        print("No jobs to export.")
        return output_path

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([dict(job) for job in jobs], f, indent=2, ensure_ascii=False)

    print(f"Exported {len(jobs)} jobs → {output_path}")
    return output_path
