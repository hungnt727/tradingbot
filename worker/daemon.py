"""Worker daemon entrypoint (Phase 6 slice 0006).

Single-threaded polling loop:

    while True:
        reap_stuck_processes()
        for pid in query_due_process_ids():
            run_one_process(pid)
        sleep(SLEEP_SECONDS)

No external scheduler — the DB drives both the schedule (due query) and the
status (last_run_status). Run with ``python -m worker.daemon``.
"""
import os
import time

from dotenv import load_dotenv
from loguru import logger

from app_db.session import SessionLocal
from worker.reaper import reap_stuck_processes
from worker.runner import run_one_process
from worker.scheduling import query_due_process_ids

load_dotenv()

# 10s keeps force-run ("Quét ngay") responsive (≤30s click→result). CPU cost is
# negligible: each idle tick is one indexed SELECT. Override via env if needed.
SLEEP_SECONDS = int(os.getenv("WORKER_SLEEP_SECONDS", "10"))


def run_once(session_factory) -> int:
    """One loop iteration: reap, then run all due processes. Returns count run."""
    reap_stuck_processes(session_factory)
    due = query_due_process_ids(session_factory)
    for pid in due:
        try:
            result = run_one_process(session_factory, pid)
            logger.info(f"[worker] process {pid} -> {result.status} "
                        f"(signals={result.signals_inserted}, tg={result.telegram_sent})")
        except Exception:  # noqa: BLE001 — never let one process kill the loop
            logger.exception(f"[worker] unhandled error running process {pid}")
    return len(due)


def main() -> None:
    logger.info(f"worker started (sleep={SLEEP_SECONDS}s)")
    while True:
        try:
            run_once(SessionLocal)
        except Exception:  # noqa: BLE001
            logger.exception("[worker] loop iteration failed")
        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    main()
