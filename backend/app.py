from __future__ import annotations

import os
import secrets
import json
import threading
from io import BytesIO
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlencode

import requests
from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field

from .auth import assert_user_scope, get_auth_context, issue_access_token, require_permission
from .db import (
    add_user_source,
    bootstrap_admin_user,
    consume_unsubscribe_token,
    consume_oauth_state,
    count_recent_auth_attempts,
    create_vc_meeting_request,
    create_oauth_state,
    create_or_update_user,
    content_quality_audit,
    get_vc_profile,
    get_latest_vc_dd_report,
    get_grad_dd_profile,
    get_latest_grad_dd_report,
    get_event_by_id,
    get_events_next_month,
    get_insight_by_id,
    get_top_events_by_region,
    get_top_insights_balanced,
    insert_vc_outreach_log,
    list_vc_candidates,
    get_top_items_for_role,
    get_user_by_email,
    get_user_by_id,
    init_db,
    list_events,
    list_insights,
    list_subscribers,
    log_email_delivery,
    log_auth_attempt,
    mark_user_email_invalid,
    cleanup_low_quality_content,
    set_user_daily_subscription,
    set_candidate_meeting_status,
    set_candidate_outreach_status,
    upsert_vc_profile,
    upsert_user_identity,
    update_subscriber,
    update_event,
    update_insight,
    delete_event,
    delete_insight,
)
from .dd_chat import dd_chat
from .digest import build_daily_digest_html, send_daily_digest
from .dd_reports import (
    generate_grad_dd_report_direct,
    generate_vc_dd_report_direct,
    generate_vc_dd_report,
    get_grad_dd_list,
    get_grad_dd_latest,
    get_vc_dd_list,
    run_grad_lab_dd,
    shortlist_grad_labs,
)
from .pipeline_runner import run_pipeline_job
from .scheduler import run_scheduler
from .localizer import localize_existing_content
from .user_source_agent import run_user_source_agent
from .vc_scout import run_vc_scout, shortlist_vc_candidates
from .emailer import get_email_config, send_email
from .observability import init_sentry
from .security import engine as security_engine

TZ_TAIPEI = timezone(timedelta(hours=8))


class SubscribeEmailPayload(BaseModel):
    email: EmailStr
    role: str = Field(default="tech", pattern="^(vc|biz|tech)$")
    subscribe_daily: bool = True
    send_now: bool = True


class UserSourcePayload(BaseModel):
    user_id: int
    url: str


class UserSourceRunPayload(BaseModel):
    user_id: int


class SubscriberUpdatePayload(BaseModel):
    subscribe_daily: Optional[bool] = None
    role: Optional[str] = Field(default=None, pattern="^(admin|vc|biz|tech)$")
    is_email_valid: Optional[bool] = None
    is_active: Optional[bool] = None


class EventUpdatePayload(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    url: Optional[str] = None
    organizer: Optional[str] = None
    region: Optional[str] = Field(default=None, pattern="^(taiwan|global)$")
    score: Optional[float] = None


class InsightUpdatePayload(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    why_it_matters: Optional[str] = None
    category: Optional[str] = Field(default=None, pattern="^(ai_tech|product_biz)$")
    content_type: Optional[str] = Field(default=None, pattern="^(paper|post|web)$")


class PipelineRunPayload(BaseModel):
    paper_days: int = Field(default=14, ge=1, le=60)
    post_days: int = Field(default=7, ge=1, le=30)
    event_days: int = Field(default=60, ge=7, le=180)
    web_past_days: int = Field(default=7, ge=1, le=30)
    web_future_days: int = Field(default=7, ge=1, le=30)


class VCProfilePayload(BaseModel):
    user_id: int
    firm_name: str
    thesis: str = ""
    preferred_stages: List[str] = Field(default_factory=list)
    preferred_sectors: List[str] = Field(default_factory=list)
    preferred_geo: str = "global"


class VCScoutPayload(BaseModel):
    user_id: int
    target_count: int = Field(default=50, ge=20, le=80)
    source_urls: List[str] = Field(default_factory=list)


class VCShortlistPayload(BaseModel):
    user_id: int
    candidate_ids: List[int] = Field(default_factory=list)


class VCOutreachPayload(BaseModel):
    user_id: int
    candidate_ids: List[int] = Field(default_factory=list)
    sender_name: str = "AI Insight Pulse"
    send_email_now: bool = False


class VCMeetingPayload(BaseModel):
    candidate_id: int
    proposed_slots: List[str] = Field(default_factory=list)


class VCDDReportPayload(BaseModel):
    user_id: int
    candidate_id: int
    extra_urls: List[str] = Field(default_factory=list)


class VCDirectReportPayload(BaseModel):
    user_id: Optional[int] = None
    company_name: Optional[str] = None
    company_url: Optional[str] = None
    extra_urls: List[str] = Field(default_factory=list)


class GradDDPayload(BaseModel):
    user_id: Optional[int] = None
    resume_text: str
    target_schools: List[str]
    interests: List[str] = Field(default_factory=list)
    degree_target: str = Field(default="master", pattern="^(master|phd|both)$")
    target_count: int = Field(default=30, ge=10, le=60)


class GradShortlistPayload(BaseModel):
    user_id: Optional[int] = None
    candidate_ids: List[int] = Field(default_factory=list)


class GradDirectReportPayload(BaseModel):
    user_id: Optional[int] = None
    resume_text: str = ""
    target_school: Optional[str] = None
    lab_url: Optional[str] = None
    professor_name: Optional[str] = None
    interests: List[str] = Field(default_factory=list)
    degree_target: str = Field(default="master", pattern="^(master|phd|both)$")


class LocalizePayload(BaseModel):
    limit_insights: int = Field(default=200, ge=1, le=2000)
    limit_events: int = Field(default=200, ge=1, le=2000)


class DDChatPayload(BaseModel):
    mode: str = Field(pattern="^(company|academic)$")
    user_id: Optional[int] = None
    message: str
    candidate_id: Optional[int] = None


class DDPdfPayload(BaseModel):
    mode: str = Field(pattern="^(company|academic)$")
    user_id: Optional[int] = None
    candidate_id: Optional[int] = None


cors_origins = [
    x.strip()
    for x in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
    if x.strip()
]

app = FastAPI(title="AI Insight Pulse API", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_scheduler_thread: Optional[threading.Thread] = None


@app.on_event("startup")
def startup() -> None:
    global _scheduler_thread
    init_sentry()
    init_db()
    admin_email = os.getenv("ADMIN_BOOTSTRAP_EMAIL", "").strip().lower()
    if admin_email:
        try:
            bootstrap_admin_user(admin_email)
        except Exception:
            pass
    auto_start_scheduler = os.getenv("AUTO_START_SCHEDULER", "1") == "1"
    if auto_start_scheduler and (_scheduler_thread is None or not _scheduler_thread.is_alive()):
        _scheduler_thread = threading.Thread(target=run_scheduler, daemon=True, name="ai-pulse-scheduler")
        _scheduler_thread.start()


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    ip = _client_ip(request)
    path = request.url.path or ""

    if security_engine.is_blacklisted(ip):
        return JSONResponse(status_code=403, content={"detail": "此 IP 已被封鎖，請稍後再試"})

    ip_limit = security_engine.check_ip_rate_limit(ip)
    if not ip_limit.allowed:
        security_engine.blacklist_ip(ip, "ip_rate_limit_exceeded")
        return JSONResponse(status_code=429, content={"detail": "請求過於頻繁（IP）"})

    body_text = ""
    content_type = request.headers.get("content-type", "").lower()
    should_inspect_body = request.method in {"POST", "PUT", "PATCH", "DELETE"} and "multipart/form-data" not in content_type
    if should_inspect_body:
        try:
            body_bytes = await request.body()
            if body_bytes:
                body_text = body_bytes.decode("utf-8", errors="ignore")
        except Exception:
            body_text = ""

    suspicious = security_engine.inspect_payload(f"{path}?{request.url.query}\n{body_text}")
    if suspicious:
        count = security_engine.register_waf_violation(ip, suspicious)
        return JSONResponse(status_code=403, content={"detail": f"請求遭 WAF 阻擋 ({count})"})

    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        try:
            ctx = get_auth_context(request)
            user_limit = security_engine.check_user_rate_limit(ctx.user_id)
            if not user_limit.allowed:
                return JSONResponse(status_code=429, content={"detail": "請求過於頻繁（User）"})
        except Exception:
            pass

    return await call_next(request)


@app.middleware("http")
async def admin_guard_middleware(request: Request, call_next):
    path = request.url.path or ""
    if not path.startswith("/admin"):
        return await call_next(request)

    required_permission = "admin_read" if request.method.upper() in {"GET", "HEAD", "OPTIONS"} else "admin_write"
    try:
        ctx = require_permission(request, required_permission)
        allowlist = _admin_allowlist_emails()
        if ctx.email.strip().lower() not in allowlist:
            return JSONResponse(status_code=403, content={"detail": "此帳號不在後台白名單"})
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _admin_allowlist_emails() -> Set[str]:
    raw = os.getenv(
        "ADMIN_ALLOWLIST_EMAILS",
        "dkhong0729@gmail.com,yoshikuni2046@gmail.com",
    )
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def _assert_not_rate_limited(request: Request, action: str, email: Optional[str] = None, limit: int = 20) -> None:
    ip = _client_ip(request)
    count = count_recent_auth_attempts(action=action, ip=ip, email=email, minutes=15)
    if count >= limit:
        raise HTTPException(status_code=429, detail="操作過於頻繁，請 15 分鐘後再試")


def _google_config() -> Dict[str, str]:
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", ""),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"),
    }


def _parse_list_field(raw: str) -> List[str]:
    text = (raw or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    values: List[str] = []
    for line in text.replace(";", ",").split(","):
        item = line.strip()
        if item:
            values.append(item)
    return values


def _require(request: Request, permission: str):
    return require_permission(request, permission)


def _markdown_to_pdf_bytes(title: str, markdown: str) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF 產生模組未安裝：{exc}")

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        font_name = "Helvetica"

    def _esc(text: str) -> str:
        return (
            (text or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=(title or "DD Report")[:120],
    )
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "zhTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=10,
    )
    style_h2 = ParagraphStyle(
        "zhH2",
        parent=styles["Heading2"],
        fontName=font_name,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#1f3f77"),
        spaceBefore=8,
        spaceAfter=6,
    )
    style_body = ParagraphStyle(
        "zhBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
    )

    elements = [Paragraph(_esc(title or "DD 報告"), style_title), Spacer(1, 2 * mm)]
    bullet_buffer: List[str] = []

    def _flush_bullets() -> None:
        nonlocal bullet_buffer
        if not bullet_buffer:
            return
        items = [
            ListItem(Paragraph(_esc(x), style_body), leftIndent=6, value="bullet")
            for x in bullet_buffer
        ]
        elements.append(
            ListFlowable(
                items,
                bulletType="bullet",
                start="circle",
                leftIndent=10,
                spaceAfter=4,
            )
        )
        bullet_buffer = []

    for raw in (markdown or "").splitlines():
        line = (raw or "").strip()
        if not line:
            _flush_bullets()
            elements.append(Spacer(1, 1.5 * mm))
            continue
        if line.startswith("# "):
            _flush_bullets()
            elements.append(Paragraph(_esc(line[2:].strip()), style_title))
            continue
        if line.startswith("## "):
            _flush_bullets()
            elements.append(Paragraph(_esc(line[3:].strip()), style_h2))
            continue
        if line.startswith("- "):
            bullet_buffer.append(line[2:].strip())
            continue
        _flush_bullets()
        elements.append(Paragraph(_esc(line), style_body))

    _flush_bullets()
    doc.build(elements)
    return buffer.getvalue()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/me")
def auth_me(request: Request) -> Dict[str, Any]:
    ctx = get_auth_context(request)
    return {
        "user_id": ctx.user_id,
        "email": ctx.email,
        "role": ctx.role,
        "permissions": ctx.permissions,
    }


@app.post("/pipeline/run")
def pipeline_run(request: Request, payload: Optional[PipelineRunPayload] = None) -> Dict[str, int]:
    _require(request, "pipeline_run")
    return run_pipeline_job(payload.model_dump() if payload else None, trigger_source="api")


@app.get("/mvp")
def mvp(
    role: str = Query(default="tech", pattern="^(vc|biz|tech)$"),
    limit: int = Query(default=20, ge=1, le=100),
    insight_days: int = Query(default=14, ge=1, le=60),
    event_days: int = Query(default=60, ge=7, le=180),
) -> Dict[str, Any]:
    insights = get_top_insights_balanced(limit=limit, per_source=2, role=role, lookback_days=insight_days)
    events_taiwan = get_top_events_by_region("taiwan", limit, future_days=event_days)
    events_global = get_top_events_by_region("global", limit, future_days=event_days)
    return {
        "generated_at": datetime.now(TZ_TAIPEI).isoformat(),
        "role": role,
        "insight_days": insight_days,
        "event_days": event_days,
        "insights": insights,
        "events": {
            "taiwan": events_taiwan,
            "global": events_global,
        },
    }


@app.get("/feed")
def feed(
    role: str = Query(default="tech", pattern="^(vc|biz|tech)$"),
    limit: int = 10,
    lookback_days: int = Query(default=14, ge=1, le=60),
) -> Dict[str, Any]:
    items = get_top_items_for_role(role, limit, lookback_days=lookback_days)
    return {"items": items}


@app.get("/events")
def events(limit: int = Query(default=50, ge=1, le=200), future_days: int = Query(default=60, ge=7, le=180)) -> Dict[str, Any]:
    return {"items": get_events_next_month(limit, future_days=future_days)}


@app.get("/admin/events")
def admin_list_events(request: Request, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    _require(request, "admin_read")
    return {"items": list_events(limit=limit, offset=offset)}


@app.patch("/admin/events/{event_id}")
def admin_update_event(request: Request, event_id: int, payload: EventUpdatePayload) -> Dict[str, Any]:
    _require(request, "admin_write")
    event = update_event(event_id, payload.model_dump(exclude_none=True))
    if not event:
        raise HTTPException(status_code=404, detail="找不到活動")
    return {"item": event}


@app.delete("/admin/events/{event_id}")
def admin_delete_event(request: Request, event_id: int) -> Dict[str, bool]:
    _require(request, "admin_write")
    if not get_event_by_id(event_id):
        raise HTTPException(status_code=404, detail="找不到活動")
    delete_event(event_id)
    return {"ok": True}


@app.get("/admin/insights")
def admin_list_insights(
    request: Request, limit: int = 100, offset: int = 0, content_type: Optional[str] = None
) -> Dict[str, Any]:
    _require(request, "admin_read")
    return {"items": list_insights(limit=limit, offset=offset, content_type=content_type)}


@app.patch("/admin/insights/{item_id}")
def admin_update_insight(request: Request, item_id: int, payload: InsightUpdatePayload) -> Dict[str, Any]:
    _require(request, "admin_write")
    item = update_insight(item_id, payload.model_dump(exclude_none=True))
    if not item:
        raise HTTPException(status_code=404, detail="找不到新知")
    return {"item": item}


@app.delete("/admin/insights/{item_id}")
def admin_delete_insight(request: Request, item_id: int) -> Dict[str, bool]:
    _require(request, "admin_write")
    if not get_insight_by_id(item_id):
        raise HTTPException(status_code=404, detail="找不到新知")
    delete_insight(item_id)
    return {"ok": True}


@app.get("/admin/subscribers")
def admin_list_subscribers(request: Request, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    _require(request, "admin_read")
    return {"items": list_subscribers(limit=limit, offset=offset)}


@app.patch("/admin/subscribers/{user_id}")
def admin_update_subscriber(request: Request, user_id: int, payload: SubscriberUpdatePayload) -> Dict[str, Any]:
    _require(request, "admin_write")
    item = update_subscriber(
        user_id=user_id,
        subscribe_daily=payload.subscribe_daily,
        role=payload.role,
        is_email_valid=payload.is_email_valid,
        is_active=payload.is_active,
    )
    if not item:
        raise HTTPException(status_code=404, detail="找不到訂閱者")
    return {"item": item}


@app.post("/admin/localize")
def admin_localize_content(request: Request, payload: LocalizePayload) -> Dict[str, int]:
    _require(request, "admin_write")
    return localize_existing_content(limit_insights=payload.limit_insights, limit_events=payload.limit_events)


@app.post("/admin/maintenance/cleanup")
def admin_cleanup_content(request: Request) -> Dict[str, Any]:
    _require(request, "admin_write")
    result = cleanup_low_quality_content()
    audit = content_quality_audit(limit=10)
    return {"cleanup": result, "audit": audit}


@app.get("/admin/maintenance/audit")
def admin_content_audit(request: Request, limit: int = Query(default=10, ge=1, le=100)) -> Dict[str, Any]:
    _require(request, "admin_read")
    return {"audit": content_quality_audit(limit=limit)}


@app.get("/admin/newsletter/preview")
def admin_newsletter_preview(request: Request, user_id: int, role: str = Query(default="tech", pattern="^(vc|biz|tech)$")) -> Dict[str, Any]:
    _require(request, "admin_read")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="找不到使用者")
    insights = get_top_insights_balanced(limit=10, per_source=2, role=role, lookback_days=14)
    events_tw = get_top_events_by_region("taiwan", 5, future_days=30)
    events_global = get_top_events_by_region("global", 5, future_days=30)
    html = build_daily_digest_html(
        role=role,
        insights=insights,
        events_tw=events_tw,
        events_global=events_global,
        unsubscribe_url="https://example.com/unsubscribe-preview",
    )
    return {"html": html, "email": user["email"], "role": role}


@app.get("/admin/email/status")
def admin_email_status(request: Request) -> Dict[str, Any]:
    _require(request, "admin_read")
    cfg = get_email_config()
    from_email = (cfg.from_email or "").strip().lower()
    domain = from_email.split("@", 1)[1] if "@" in from_email else ""
    return {
        "provider": cfg.provider,
        "from_email": from_email,
        "reply_to": cfg.reply_to,
        "api_key_configured": bool(cfg.api_key),
        "from_domain": domain,
        "next_step": (
            "請到 SendGrid Settings -> Sender Authentication 驗證寄件者或網域，"
            "並確保 EMAIL_FROM 使用該驗證地址。"
        ),
    }


@app.get("/auth/google/start")
def auth_google_start(request: Request, role: str = Query(default="tech", pattern="^(vc|biz|tech)$")) -> RedirectResponse:
    _assert_not_rate_limited(request, action="google_start", limit=30)
    cfg = _google_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(status_code=500, detail="Google OAuth 尚未設定")

    ip = _client_ip(request)
    state = secrets.token_urlsafe(24)
    create_oauth_state(state, ip)

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": f"{state}:{role}",
        "access_type": "online",
        "prompt": "select_account",
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    log_auth_attempt(ip=ip, action="google_start", email=None, success=True)
    return RedirectResponse(url=url)


@app.get("/auth/google/callback")
def auth_google_callback(request: Request, code: str, state: str) -> RedirectResponse:
    ip = _client_ip(request)
    try:
        raw_state, role = state.split(":", 1)
    except ValueError:
        log_auth_attempt(ip=ip, action="google_callback", email=None, success=False)
        raise HTTPException(status_code=400, detail="state 無效")

    if role not in {"vc", "biz", "tech"}:
        role = "tech"

    if not consume_oauth_state(raw_state, ip):
        log_auth_attempt(ip=ip, action="google_callback", email=None, success=False)
        raise HTTPException(status_code=400, detail="state 已過期或不合法")

    _assert_not_rate_limited(request, action="google_callback", limit=30)
    cfg = _google_config()

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": cfg["redirect_uri"],
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if token_resp.status_code >= 300:
        log_auth_attempt(ip=ip, action="google_callback", email=None, success=False)
        raise HTTPException(status_code=400, detail="Google token 交換失敗")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        log_auth_attempt(ip=ip, action="google_callback", email=None, success=False)
        raise HTTPException(status_code=400, detail="Google token 無效")

    userinfo_resp = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if userinfo_resp.status_code >= 300:
        log_auth_attempt(ip=ip, action="google_callback", email=None, success=False)
        raise HTTPException(status_code=400, detail="無法取得 Google 使用者資訊")

    info = userinfo_resp.json()
    email = (info.get("email") or "").lower().strip()
    email_verified = bool(info.get("email_verified"))
    provider_sub = info.get("sub")

    if not email_verified or not email.endswith("@gmail.com"):
        log_auth_attempt(ip=ip, action="google_callback", email=email or None, success=False)
        raise HTTPException(status_code=403, detail="僅接受已驗證的 Gmail 帳號")

    existing_user = get_user_by_email(email)
    assigned_role = "admin" if (email in _admin_allowlist_emails()) else role
    if existing_user and existing_user.get("role") == "admin":
        assigned_role = "admin"

    user = create_or_update_user(
        email=email,
        role=assigned_role,
        display_name=info.get("name"),
        is_email_verified=True,
    )
    if provider_sub:
        upsert_user_identity(int(user["id"]), "google", provider_sub, email)

    token = issue_access_token(user)
    log_auth_attempt(ip=ip, action="google_callback", email=email, success=True)

    frontend_callback = os.getenv("FRONTEND_CALLBACK_URL", "http://localhost:3000")
    params = urlencode(
        {
            "token": token,
            "user_id": str(user["id"]),
            "email": user["email"],
            "role": user["role"],
            "display_name": user.get("display_name") or "",
        }
    )
    sep = "&" if "?" in frontend_callback else "?"
    return RedirectResponse(url=f"{frontend_callback}{sep}{params}")


@app.post("/subscribe_email")
def subscribe_email(request: Request, payload: SubscribeEmailPayload) -> Dict[str, Any]:
    email = payload.email.lower().strip()
    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail="請使用 Gmail 訂閱")

    _assert_not_rate_limited(request, action="subscribe_email", email=email, limit=15)
    ip = _client_ip(request)

    user = get_user_by_email(email)
    if not user:
        user = create_or_update_user(email=email, role=payload.role, is_email_verified=True)

    set_user_daily_subscription(int(user["id"]), payload.subscribe_daily, payload.role)
    log_auth_attempt(ip=ip, action="subscribe_email", email=email, success=True)

    sent = False
    send_result: Optional[Dict[str, Any]] = None
    send_error: Optional[str] = None
    warning: Optional[str] = None
    if payload.send_now:
        try:
            send_result = send_daily_digest(int(user["id"]), payload.role)
            sent = True
        except Exception as exc:
            msg = str(exc)
            send_error = msg
            if "Sender Identity" in msg or "from address does not match a verified Sender Identity" in msg:
                warning = (
                    "訂閱成功，但立即寄送失敗：寄件者 EMAIL_FROM 尚未在 SendGrid 驗證。"
                    "請到 SendGrid Sender Authentication 完成單一寄件者或網域驗證。"
                )
            elif "ProxyError" in msg or "Unable to connect to proxy" in msg:
                warning = (
                    "訂閱成功，但立即寄送失敗：目前環境代理設定阻擋了 SendGrid 連線。"
                    "請在 backend/.env 設定 EMAIL_TRUST_ENV_PROXY=0，必要時再用 EMAIL_PROXY_URL 指定可用代理。"
                )
            else:
                warning = f"訂閱成功，但立即寄送失敗：{msg}"

    refreshed = get_user_by_id(int(user["id"])) or user
    return {
        "user_id": int(user["id"]),
        "email": refreshed.get("email"),
        "role": refreshed.get("role"),
        "subscribed": payload.subscribe_daily,
        "sent": sent,
        "send_result": send_result,
        "warning": warning,
        "send_error": send_error,
        "sendgrid_sender_guide": "https://docs.sendgrid.com/for-developers/sending-email/sender-identity",
    }


@app.get("/unsubscribe")
def unsubscribe(token: str) -> Dict[str, Any]:
    user_id = consume_unsubscribe_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="退訂連結無效或已過期")
    user = get_user_by_id(user_id)
    role = (user or {}).get("role") or "tech"
    set_user_daily_subscription(user_id, False, role)
    return {"ok": True, "message": "已成功取消訂閱每日摘要"}


@app.post("/webhooks/sendgrid")
async def sendgrid_webhook(request: Request) -> Dict[str, Any]:
    secret = os.getenv("SENDGRID_WEBHOOK_SECRET", "").strip()
    if secret:
        header_secret = request.headers.get("x-webhook-secret", "").strip()
        if not header_secret or header_secret != secret:
            raise HTTPException(status_code=401, detail="Webhook 驗證失敗")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook payload 非 JSON")

    if not isinstance(payload, list):
        payload = [payload]

    processed = 0
    invalidated = 0
    for event in payload:
        if not isinstance(event, dict):
            continue
        email = str(event.get("email") or "").strip().lower()
        event_name = str(event.get("event") or "")
        sg_message_id = str(event.get("sg_message_id") or "")
        response_code = event.get("response")
        if not email:
            continue
        processed += 1
        log_email_delivery(
            email=email,
            subject="",
            status="provider_event",
            provider="sendgrid",
            provider_message_id=sg_message_id or None,
            response_code=int(response_code) if isinstance(response_code, int) else None,
            provider_event=event_name or None,
            detail=json.dumps(event, ensure_ascii=False, default=str)[:1500],
        )
        if event_name in {"bounce", "dropped", "spamreport", "blocked"}:
            user_id = mark_user_email_invalid(email, reason=event_name)
            if user_id:
                invalidated += 1

    return {"processed": processed, "invalidated": invalidated}


@app.post("/vc/profile")
def vc_profile_upsert(request: Request, payload: VCProfilePayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, payload.user_id)
    item = upsert_vc_profile(
        user_id=payload.user_id,
        firm_name=payload.firm_name,
        thesis=payload.thesis,
        preferred_stages=payload.preferred_stages,
        preferred_sectors=payload.preferred_sectors,
        preferred_geo=payload.preferred_geo,
    )
    return {"profile": item}


@app.get("/vc/profile")
def vc_profile_get(request: Request, user_id: int) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, user_id)
    profile = get_vc_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="尚未建立 VC profile")
    return {"profile": profile}


@app.post("/vc/scout/run")
def vc_scout_run(request: Request, payload: VCScoutPayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, payload.user_id)
    try:
        return run_vc_scout(payload.user_id, payload.target_count, payload.source_urls)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/vc/scout/candidates")
def vc_candidates(
    request: Request, user_id: int, limit: int = Query(default=50, ge=1, le=100), shortlisted_only: bool = False
) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, user_id)
    profile = get_vc_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="尚未建立 VC profile")
    items = list_vc_candidates(int(profile["id"]), limit=limit, shortlisted_only=shortlisted_only)
    return {"items": items}


@app.post("/vc/scout/shortlist")
def vc_shortlist(request: Request, payload: VCShortlistPayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, payload.user_id)
    try:
        return shortlist_vc_candidates(payload.user_id, payload.candidate_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/vc/outreach")
def vc_outreach(request: Request, payload: VCOutreachPayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_scout_run")
    assert_user_scope(ctx, payload.user_id)
    profile = get_vc_profile(payload.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="尚未建立 VC profile")

    candidates = [c for c in list_vc_candidates(int(profile["id"]), limit=100, shortlisted_only=True) if c["id"] in payload.candidate_ids]
    drafts: List[Dict[str, Any]] = []
    sent_count = 0

    for c in candidates:
        subject = f"{profile['firm_name']} x {c.get('name', '團隊')}：合作與投資交流邀請"
        body = (
            f"您好，我是 {payload.sender_name}，目前代表 {profile['firm_name']}。\n\n"
            f"我們關注到你們的項目：{c.get('name', '')}\n"
            f"關注原因：{c.get('rationale', '')}\n\n"
            "若你願意，我們希望安排 30 分鐘線上交流，了解團隊與產品進度。\n"
            "請回覆你方便的時段，謝謝。"
        )
        sent = False
        if payload.send_email_now and c.get("contact_email"):
            try:
                send_email(c["contact_email"], subject, body.replace("\n", "<br/>"))
                sent = True
                sent_count += 1
                set_candidate_outreach_status(int(c["id"]), "sent")
            except Exception:
                sent = False
        insert_vc_outreach_log(int(c["id"]), payload.user_id, subject, body, sent)
        drafts.append({"candidate_id": c["id"], "subject": subject, "body": body, "sent": sent})

    return {"count": len(drafts), "sent": sent_count, "drafts": drafts}


@app.post("/vc/meeting/propose")
def vc_meeting_propose(request: Request, payload: VCMeetingPayload) -> Dict[str, Any]:
    _require(request, "vc_dd_run")
    item = create_vc_meeting_request(payload.candidate_id, payload.proposed_slots)
    set_candidate_meeting_status(payload.candidate_id, "proposed")
    return {"meeting_request": item}


@app.post("/vc/dd/report")
def vc_dd_report(request: Request, payload: VCDDReportPayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_dd_run")
    assert_user_scope(ctx, payload.user_id)
    try:
        return generate_vc_dd_report(payload.user_id, payload.candidate_id, payload.extra_urls)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/dd/company/report/direct")
def vc_dd_report_direct(request: Request, payload: VCDirectReportPayload) -> Dict[str, Any]:
    ctx = _require(request, "vc_dd_run")
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return generate_vc_dd_report_direct(
            user_id=target_user_id,
            company_name=payload.company_name,
            company_url=payload.company_url,
            extra_urls=payload.extra_urls,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/vc/dd/reports")
def vc_dd_reports(request: Request, user_id: int, limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    ctx = _require(request, "vc_dd_run")
    assert_user_scope(ctx, user_id)
    try:
        return get_vc_dd_list(user_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/grad/dd/run")
def grad_dd_run(request: Request, payload: GradDDPayload) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    return run_grad_lab_dd(
        user_id=target_user_id,
        resume_text=payload.resume_text,
        target_schools=payload.target_schools,
        interests=payload.interests,
        degree_target=payload.degree_target,
        target_count=payload.target_count,
    )


@app.post("/grad/dd/run_upload")
async def grad_dd_run_upload(
    request: Request,
    user_id: Optional[int] = Form(default=None),
    target_schools: str = Form(...),
    interests: str = Form(default=""),
    degree_target: str = Form(default="master"),
    target_count: int = Form(default=30),
    resume_file: UploadFile = File(...),
) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    if degree_target not in {"master", "phd", "both"}:
        raise HTTPException(status_code=400, detail="degree_target 僅允許 master / phd / both")
    if target_count < 10 or target_count > 60:
        raise HTTPException(status_code=400, detail="target_count 需介於 10 到 60")

    raw_bytes = await resume_file.read()
    if len(raw_bytes) > 2_000_000:
        raise HTTPException(status_code=400, detail="履歷檔案過大，請控制在 2MB 內")

    resume_text = ""
    filename = (resume_file.filename or "").lower()
    if filename.endswith(".txt") or filename.endswith(".md"):
        try:
            resume_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            resume_text = raw_bytes.decode("utf-8", errors="ignore")
    elif filename.endswith(".pdf"):
        try:
            from pypdf import PdfReader  # type: ignore

            import io

            reader = PdfReader(io.BytesIO(raw_bytes))
            resume_text = "\n".join([(p.extract_text() or "") for p in reader.pages])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"PDF 解析失敗：{exc}")
    else:
        raise HTTPException(status_code=400, detail="僅支援 .txt / .md / .pdf 履歷檔")

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="履歷內容為空，請確認檔案內容")

    schools = _parse_list_field(target_schools)
    if not schools:
        raise HTTPException(status_code=400, detail="請提供至少一個目標學校")
    interest_list = _parse_list_field(interests)

    return run_grad_lab_dd(
        user_id=target_user_id,
        resume_text=resume_text,
        target_schools=schools,
        interests=interest_list,
        degree_target=degree_target,
        target_count=target_count,
    )


@app.get("/grad/dd/latest")
def grad_dd_latest(request: Request, user_id: Optional[int] = None) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return get_grad_dd_latest(target_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/grad/dd/reports")
def grad_dd_reports(request: Request, user_id: Optional[int] = None, limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return get_grad_dd_list(target_user_id, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/grad/dd/shortlist")
def grad_dd_shortlist(request: Request, payload: GradShortlistPayload) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return shortlist_grad_labs(target_user_id, payload.candidate_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/dd/academic/report/direct")
def grad_dd_report_direct(request: Request, payload: GradDirectReportPayload) -> Dict[str, Any]:
    ctx = _require(request, "grad_dd_run")
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return generate_grad_dd_report_direct(
            user_id=target_user_id,
            resume_text=payload.resume_text,
            target_school=payload.target_school,
            lab_url=payload.lab_url,
            professor_name=payload.professor_name,
            interests=payload.interests,
            degree_target=payload.degree_target,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/dd/chat")
def dd_chat_endpoint(request: Request, payload: DDChatPayload) -> Dict[str, Any]:
    perm = "vc_dd_run" if payload.mode == "company" else "grad_dd_run"
    ctx = _require(request, perm)
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)
    try:
        return dd_chat(
            mode=payload.mode,
            user_id=target_user_id,
            message=payload.message,
            candidate_id=payload.candidate_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/dd/report/pdf")
def dd_report_pdf(request: Request, payload: DDPdfPayload) -> Response:
    perm = "vc_dd_run" if payload.mode == "company" else "grad_dd_run"
    ctx = _require(request, perm)
    target_user_id = payload.user_id or ctx.user_id
    assert_user_scope(ctx, target_user_id)

    if payload.mode == "company":
        profile = get_vc_profile(target_user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到 VC profile")
        report = get_latest_vc_dd_report(int(profile["id"]), candidate_id=payload.candidate_id)
        if not report:
            raise HTTPException(status_code=404, detail="尚未生成公司 DD 報告")
        title = report.get("title") or "公司 DD 報告"
        markdown = report.get("markdown") or ""
    else:
        profile = get_grad_dd_profile(target_user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="找不到學術 DD profile")
        report = get_latest_grad_dd_report(int(profile["id"]))
        if not report:
            raise HTTPException(status_code=404, detail="尚未生成學術 DD 報告")
        title = "學術 DD 報告"
        markdown = report.get("markdown") or ""

    pdf_bytes = _markdown_to_pdf_bytes(str(title), str(markdown))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''dd-report-{payload.mode}.pdf",
    }
    return Response(content=pdf_bytes, media_type="application/pdf", headers=headers)


@app.post("/sources")
def add_source(request: Request, payload: UserSourcePayload) -> Dict[str, int]:
    ctx = _require(request, "manage_subscription")
    assert_user_scope(ctx, payload.user_id)
    source_id = add_user_source(payload.user_id, payload.url)
    return {"id": source_id}


@app.post("/sources/run")
def run_sources(request: Request, payload: UserSourceRunPayload) -> Dict[str, int]:
    ctx = _require(request, "manage_subscription")
    assert_user_scope(ctx, payload.user_id)
    return run_user_source_agent(payload.user_id)


@app.post("/deliver")
def deliver(request: Request, user_id: int, role: str = Query(default="tech", pattern="^(vc|biz|tech)$")) -> Dict[str, Any]:
    ctx = _require(request, "manage_subscription")
    assert_user_scope(ctx, user_id)
    result = send_daily_digest(user_id, role)
    return {"sent": True, "result": result}
