import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def log_crawl_job(
    job_id: str,
    dataset_name: str,
    source: str,
    status: str,
    records_written: int,
    records_read: int = 0,
    error: str = "",
    error_count: int = 0,
    retry_count: int = 0,
    fallback_used: bool = False,
    fallback_reason: str = "",
    coverage_status: str = "ok",
    started_at: str = None
):
    log_dir = BASE_DIR / "data" / "experiments" / "crawl_jobs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_entry = {
        "job_id": job_id,
        "dataset_name": dataset_name,
        "source": source,
        "status": status,
        "records_read": records_read,
        "records_written": records_written,
        "error_count": error_count,
        "retry_count": retry_count,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "coverage_status": coverage_status,
        "error": error,
        "started_at": started_at or datetime.utcnow().isoformat() + "Z",
        "finished_at": datetime.utcnow().isoformat() + "Z"
    }

    log_file = log_dir / f"{job_id}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2)

def log_data_quality_issue(job_id: str, dataset_name: str, issue_type: str, details: str, severity: str = "warning"):
    log_dir = BASE_DIR / "data" / "experiments" / "data_quality_issues"
    log_dir.mkdir(parents=True, exist_ok=True)

    issue_id = f"{job_id}_{datetime.utcnow().timestamp()}"
    log_entry = {
        "issue_id": issue_id,
        "job_id": job_id,
        "dataset_name": dataset_name,
        "issue_type": issue_type,
        "severity": severity,
        "details": details,
        "logged_at": datetime.utcnow().isoformat() + "Z"
    }

    log_file = log_dir / f"{issue_id}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2)
