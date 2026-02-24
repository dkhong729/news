from __future__ import annotations

import os


def init_sentry() -> None:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except Exception:
        return

    env = os.getenv("SENTRY_ENV", os.getenv("APP_ENV", "development"))
    traces_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1"))

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        integrations=[FastApiIntegration()],
        traces_sample_rate=max(0.0, min(1.0, traces_rate)),
        send_default_pii=False,
    )
