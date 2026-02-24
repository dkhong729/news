from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import List

from .db import (
    create_unsubscribe_token,
    get_top_events_by_region,
    get_top_insights_balanced,
    get_user_by_id,
    log_email_delivery,
)
from .emailer import send_email

TZ_TAIPEI = timezone(timedelta(hours=8))


def _render_items(items: List[dict]) -> str:
    cards = []
    for idx, item in enumerate(items, 1):
        cards.append(
            """
            <tr>
              <td style='padding:12px 0;border-bottom:1px solid #eceff3;'>
                <div style='font-size:12px;color:#667085;'>#{rank} · 分數 {score}</div>
                <div style='font-size:16px;font-weight:700;color:#0f172a;line-height:1.4;margin:4px 0;'>{title}</div>
                <div style='font-size:13px;color:#334155;line-height:1.6;'>{summary}</div>
                <div style='margin-top:6px;font-size:13px;color:#0f172a;'><strong>為何重要：</strong>{why}</div>
                <div style='margin-top:8px;'><a href='{url}' style='font-size:13px;color:#0f766e;text-decoration:none;'>閱讀原文 ↗</a></div>
              </td>
            </tr>
            """.format(
                rank=idx,
                score=item.get("final_score", "-"),
                title=item.get("title", ""),
                summary=item.get("summary", ""),
                why=item.get("why_it_matters", ""),
                url=item.get("url", "#"),
            )
        )
    return "".join(cards)


def _render_events(title: str, events: List[dict]) -> str:
    rows = []
    for ev in events:
        date_text = ev.get("start_at") or "時間待更新"
        rows.append(
            """
            <tr>
              <td style='padding:10px 0;border-bottom:1px solid #eceff3;'>
                <div style='font-size:15px;font-weight:700;color:#0f172a;'>{title}</div>
                <div style='font-size:13px;color:#334155;'>時間：{date}</div>
                <div style='font-size:13px;color:#334155;'>{summary}</div>
                <a href='{url}' style='font-size:13px;color:#0f766e;text-decoration:none;'>查看活動 ↗</a>
              </td>
            </tr>
            """.format(
                title=ev.get("title", ""),
                date=date_text,
                summary=ev.get("description", ""),
                url=ev.get("url") or "#",
            )
        )

    return (
        f"<h3 style='margin:18px 0 8px;font-size:18px;color:#0f172a;'>{title}</h3>"
        f"<table width='100%' cellspacing='0' cellpadding='0'>{''.join(rows)}</table>"
    )


def send_daily_digest(user_id: int, role: str = "tech") -> dict:
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("找不到使用者")

    insights = get_top_insights_balanced(limit=10, per_source=2, role=role, lookback_days=14)
    events_tw = get_top_events_by_region("taiwan", 5, future_days=30)
    events_global = get_top_events_by_region("global", 5, future_days=30)

    token = create_unsubscribe_token(user_id, ttl_days=30)
    public_base = (os.getenv("PUBLIC_API_BASE_URL", "http://localhost:8000")).rstrip("/")
    unsubscribe_url = f"{public_base}/unsubscribe?token={token}"
    unsubscribe_mailto = os.getenv("EMAIL_UNSUBSCRIBE_MAILTO", f"mailto:{os.getenv('EMAIL_FROM', 'no-reply@aiinsightpulse.com')}")

    now_label = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")

    html = build_daily_digest_html(
        role=role,
        insights=insights,
        events_tw=events_tw,
        events_global=events_global,
        unsubscribe_url=unsubscribe_url,
    )

    headers = {
        "List-Unsubscribe": f"<{unsubscribe_mailto}>, <{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }

    try:
        result = send_email(user["email"], "AI Insight Pulse 每日摘要", html, headers=headers)
        log_email_delivery(
            email=user["email"],
            subject="AI Insight Pulse 每日摘要",
            status="sent",
            provider=result.get("provider") or "unknown",
            provider_message_id=result.get("message_id"),
            response_code=int(result.get("status")) if (result.get("status") or "").isdigit() else None,
            detail="daily_digest",
            user_id=user_id,
        )
        return {
            "sent": True,
            "provider": result.get("provider") or "unknown",
            "message_id": result.get("message_id"),
            "status": result.get("status"),
        }
    except Exception as exc:
        log_email_delivery(
            email=user["email"],
            subject="AI Insight Pulse 每日摘要",
            status="failed",
            provider=os.getenv("EMAIL_PROVIDER", "unknown"),
            detail=str(exc)[:500],
            user_id=user_id,
        )
        raise


def build_daily_digest_html(
    role: str,
    insights: List[dict],
    events_tw: List[dict],
    events_global: List[dict],
    unsubscribe_url: str,
) -> str:
    now_label = datetime.now(TZ_TAIPEI).strftime("%Y-%m-%d %H:%M")
    return f"""
    <div style='margin:0;padding:0;background:#f4f6fb;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'>
      <div style='max-width:760px;margin:24px auto;background:#ffffff;border-radius:16px;padding:24px 28px;border:1px solid #e6e8ec;'>
        <div style='display:flex;justify-content:space-between;align-items:flex-start;gap:12px;'>
          <div>
            <div style='font-size:12px;letter-spacing:1px;color:#0f766e;font-weight:700;'>AI INSIGHT PULSE</div>
            <h2 style='margin:6px 0 8px;font-size:24px;color:#0f172a;'>每日 AI 情報電子報</h2>
            <div style='font-size:13px;color:#64748b;'>更新時間：{now_label}（台北）</div>
          </div>
          <div style='font-size:12px;color:#64748b;background:#f1f5f9;padding:6px 10px;border-radius:20px;'>角色：{role}</div>
        </div>

        <h3 style='margin:22px 0 8px;font-size:18px;color:#0f172a;'>今日新知 Top 10</h3>
        <table width='100%' cellspacing='0' cellpadding='0'>{_render_items(insights)}</table>

        {_render_events('台灣 AI / 新創活動（未來 30 天）', events_tw)}
        {_render_events('全球技術活動（未來 30 天）', events_global)}

        <hr style='border:none;border-top:1px solid #e6e8ec;margin:18px 0;' />
        <div style='font-size:12px;color:#64748b;line-height:1.7;'>
          你收到這封信是因為已開啟每日摘要訂閱。<br/>
          取消訂閱：<a href='{unsubscribe_url}' style='color:#0f766e;text-decoration:none;'>一鍵取消</a>
        </div>
      </div>
    </div>
    """
