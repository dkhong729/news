from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .db import list_daily_subscribers, was_daily_digest_sent_on_date
from .digest import send_daily_digest
from .pipeline_runner import run_pipeline_job


def run_scheduler() -> None:
    ingest_interval_hours = int(os.getenv("INGEST_INTERVAL_HOURS", "6"))
    target_hour = int(os.getenv("DIGEST_HOUR", "8"))
    target_minute = int(os.getenv("DIGEST_MINUTE", "0"))
    digest_timezone = os.getenv("DIGEST_TIMEZONE", "Asia/Taipei")
    check_interval_sec = int(os.getenv("SCHEDULER_CHECK_INTERVAL_SEC", "30"))
    try:
        tz = ZoneInfo(digest_timezone)
    except Exception:
        tz = ZoneInfo("Asia/Taipei")
        digest_timezone = "Asia/Taipei"

    last_ingest_at: datetime | None = None
    last_digest_date = None  # scheduler process memory guard

    while True:
        now = datetime.now(tz)

        should_ingest = (
            last_ingest_at is None
            or now - last_ingest_at >= timedelta(hours=ingest_interval_hours)
        )
        if should_ingest:
            try:
                run_pipeline_job(trigger_source="scheduler")
                last_ingest_at = now
            except Exception:
                pass

        should_send_digest_now = (
            (now.hour > target_hour or (now.hour == target_hour and now.minute >= target_minute))
            and last_digest_date != now.date()
        )
        if should_send_digest_now:
            subscribers = list_daily_subscribers()
            for user in subscribers:
                try:
                    uid = int(user["id"])
                    if was_daily_digest_sent_on_date(uid, now.date(), timezone_name=digest_timezone):
                        continue
                    send_daily_digest(uid, user.get("role") or "tech")
                except Exception:
                    continue
            last_digest_date = now.date()

        time.sleep(max(10, check_interval_sec))


if __name__ == "__main__":
    run_scheduler()
