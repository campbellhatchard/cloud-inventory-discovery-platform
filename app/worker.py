from __future__ import annotations

import os
import socket
import threading
import time
import traceback
from collections.abc import Iterable

from .ai_service import process_ai_job
from .config import Settings, get_settings
from .database import SessionLocal
from .jobs import claim_next, complete, fail
from .maintenance import run_maintenance
from .models import WorkerHeartbeat, utcnow
from .publication_service import process_publication
from .storage import storage_configuration_status


LANES: dict[str, tuple[str, ...]] = {
    "fast-text": ("FAST_TEXT",),
    "photo-analysis": ("PHOTO_ANALYSIS",),
    "general-ai": ("GENERAL_AI", "STANDARD"),
    "publication": ("PUBLICATION",),
}


def _touch_heartbeat(settings: Settings, *, status: str = "RUNNING", details: dict | None = None) -> None:
    storage_status = storage_configuration_status(settings)
    with SessionLocal() as db:
        heartbeat = db.get(WorkerHeartbeat, "worker")
        payload = {
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "ai_enabled": settings.ai_enabled,
            "ai_model": settings.openai_model,
            "confidential_ai_enabled": settings.ai_confidential_content_enabled,
            "data_control_mode": settings.openai_data_control_mode,
            "queue_lanes": sorted(LANES),
            **(details or {}),
        }
        if heartbeat:
            heartbeat.app_version = settings.app_version
            heartbeat.status = status
            heartbeat.storage_configured = bool(storage_status.get("configured"))
            heartbeat.details = payload
            heartbeat.last_seen_at = utcnow()
        else:
            db.add(
                WorkerHeartbeat(
                    component="worker",
                    app_version=settings.app_version,
                    status=status,
                    storage_configured=bool(storage_status.get("configured")),
                    details=payload,
                    last_seen_at=utcnow(),
                )
            )
        db.commit()


def run_once(
    worker_id: str | None = None,
    *,
    queue_names: Iterable[str] | None = None,
) -> bool:
    settings = get_settings()
    worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    with SessionLocal() as db:
        job = claim_next(db, worker_id, queue_names=queue_names)
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


def _lane_loop(lane_name: str, queue_names: tuple[str, ...], settings: Settings) -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{lane_name}"
    print(f"Worker lane started: {lane_name} -> {', '.join(queue_names)}")
    while True:
        try:
            worked = run_once(worker_id, queue_names=queue_names)
        except Exception:
            traceback.print_exc()
            time.sleep(max(5.0, settings.job_poll_seconds))
            continue
        if not worked:
            time.sleep(settings.job_poll_seconds)


def main() -> None:
    settings = get_settings()
    print("Cloud Inventory discovery worker started.")
    _touch_heartbeat(settings, details={"event": "started", "lanes": sorted(LANES)})

    for lane_name, queue_names in LANES.items():
        thread = threading.Thread(
            target=_lane_loop,
            args=(lane_name, queue_names, settings),
            name=f"ci-{lane_name}",
            daemon=True,
        )
        thread.start()

    next_maintenance_at = 0.0
    next_heartbeat_at = 0.0
    while True:
        now = time.monotonic()
        if now >= next_heartbeat_at:
            try:
                _touch_heartbeat(settings, details={"event": "polling", "lanes": sorted(LANES)})
            except Exception:
                traceback.print_exc()
            next_heartbeat_at = now + 60.0
        if now >= next_maintenance_at:
            try:
                with SessionLocal() as db:
                    result = run_maintenance(db, settings)
                if any(result.values()):
                    print(f"Maintenance completed: {result}")
            except Exception:
                traceback.print_exc()
            next_maintenance_at = now + settings.maintenance_interval_seconds
        time.sleep(max(1.0, min(5.0, settings.job_poll_seconds)))


if __name__ == "__main__":
    main()
