from __future__ import annotations

import os
import socket
import time
import traceback

from .ai_service import process_ai_job
from .config import get_settings
from .database import SessionLocal
from .jobs import claim_next, complete, fail
from .maintenance import run_maintenance
from .publication_service import process_publication


def run_once(worker_id: str | None = None) -> bool:
    settings = get_settings()
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    with SessionLocal() as db:
        job = claim_next(db, worker_id)
        if not job:
            return False
        try:
            if job.job_type == "publication.generate":
                process_publication(db, job.payload["publication_id"], settings)
            elif job.job_type == "ai.generate":
                process_ai_job(db, job.payload["ai_job_id"], settings)
            else:
                raise ValueError(f"Unknown job type: {job.job_type}")
            complete(db, job)
        except Exception as exc:
            traceback.print_exc()
            fail(db, job, str(exc))
        return True


def main() -> None:
    settings = get_settings()
    print("Cloud Inventory discovery worker started.")
    next_maintenance_at = 0.0
    while True:
        now = time.monotonic()
        if now >= next_maintenance_at:
            try:
                with SessionLocal() as db:
                    result = run_maintenance(db, settings)
                if any(result.values()):
                    print(f"Maintenance completed: {result}")
            except Exception:
                traceback.print_exc()
            next_maintenance_at = now + settings.maintenance_interval_seconds
        try:
            worked = run_once()
        except Exception:
            traceback.print_exc()
            time.sleep(max(5.0, settings.job_poll_seconds))
            continue
        if not worked:
            time.sleep(settings.job_poll_seconds)


if __name__ == "__main__":
    main()
