from __future__ import annotations

import os
from typing import Dict, Optional

import requests

from .db import create_pipeline_run, finish_pipeline_run
from .mvp_pipeline import run_mvp_pipeline



def _notify_pipeline(status: str, trigger_source: str, result: Optional[Dict[str, int]] = None, error: Optional[str] = None) -> None:
    webhook = os.getenv("PIPELINE_ALERT_WEBHOOK", "").strip()
    if not webhook:
        return

    notify_on_success = os.getenv("PIPELINE_NOTIFY_ON_SUCCESS", "0") == "1"
    if status == "success" and not notify_on_success:
        return

    text = (
        f"[AI Insight Pulse] pipeline {status}\n"
        f"trigger={trigger_source}\n"
        f"result={result or {}}"
    )
    if error:
        text += f"\nerror={error[:500]}"

    try:
        requests.post(webhook, json={"text": text}, timeout=8)
    except Exception:
        return



def run_pipeline_job(overrides: Optional[Dict[str, int]] = None, trigger_source: str = "manual") -> Dict[str, int]:
    run_id = create_pipeline_run(trigger_source=trigger_source)
    try:
        result = run_mvp_pipeline(overrides)
        finish_pipeline_run(run_id, status="success", result_json=result)
        _notify_pipeline("success", trigger_source, result=result)
        return result
    except Exception as exc:
        finish_pipeline_run(run_id, status="failed", result_json={}, error_message=str(exc))
        _notify_pipeline("failed", trigger_source, error=str(exc))
        raise
