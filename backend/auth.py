from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

from .db import get_user_by_id, get_user_permissions

TZ_TAIPEI = timezone(timedelta(hours=8))


@dataclass
class AuthContext:
    user_id: int
    email: str
    role: str
    permissions: List[str]
    payload: Dict[str, Any]



def _jwt_secret() -> str:
    secret = os.getenv("APP_JWT_SECRET", "")
    if not secret:
        raise RuntimeError("APP_JWT_SECRET 尚未設定")
    return secret



def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")



def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + padding).encode("utf-8"))



def issue_access_token(user: Dict[str, Any]) -> str:
    role = str(user.get("role") or "tech")
    user_id = int(user["id"])
    permissions = get_user_permissions(user_id, fallback_role=role)
    now = datetime.now(TZ_TAIPEI)
    payload = {
        "sub": str(user_id),
        "email": user.get("email", ""),
        "role": role,
        "permissions": permissions,
        "exp": int((now + timedelta(days=7)).timestamp()),
        "iat": int(now.timestamp()),
    }
    body = _b64url_encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_jwt_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}"



def verify_access_token(token: str) -> Dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Token 格式錯誤")

    expected = hmac.new(_jwt_secret().encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    try:
        provided = _b64url_decode(sig)
    except Exception:
        raise HTTPException(status_code=401, detail="Token 簽名錯誤")

    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Token 驗證失敗")

    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="Token 內容錯誤")

    exp = int(payload.get("exp") or 0)
    now_ts = int(datetime.now(TZ_TAIPEI).timestamp())
    if exp <= now_ts:
        raise HTTPException(status_code=401, detail="Token 已過期")
    return payload



def _extract_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = header.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Token 不可為空")
    return token



def get_auth_context(request: Request) -> AuthContext:
    token = _extract_token(request)
    payload = verify_access_token(token)
    try:
        user_id = int(payload.get("sub"))
    except Exception:
        raise HTTPException(status_code=401, detail="Token sub 錯誤")

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="使用者不存在")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="帳號已停用")

    role = str(user.get("role") or payload.get("role") or "tech")
    perms = get_user_permissions(user_id, fallback_role=role)
    return AuthContext(
        user_id=user_id,
        email=str(user.get("email") or payload.get("email") or ""),
        role=role,
        permissions=perms,
        payload=payload,
    )



def require_permission(request: Request, permission_code: str) -> AuthContext:
    ctx = get_auth_context(request)
    if permission_code not in set(ctx.permissions):
        hints = {
            "vc_scout_run": "此功能用於公司 DD/VC Scout，需啟用公司盡調權限",
            "vc_dd_run": "此功能用於公司 DD 報告生成",
            "grad_dd_run": "此功能用於學術 DD",
            "admin_read": "此功能僅限後台管理員",
            "admin_write": "此功能僅限後台管理員（可寫入）",
        }
        hint = hints.get(permission_code)
        if hint:
            raise HTTPException(status_code=403, detail=f"缺少權限：{permission_code}（{hint}）")
        raise HTTPException(status_code=403, detail=f"缺少權限：{permission_code}")
    return ctx



def assert_user_scope(ctx: AuthContext, target_user_id: int) -> None:
    if target_user_id == ctx.user_id:
        return
    if "admin_write" in set(ctx.permissions):
        return
    raise HTTPException(status_code=403, detail="不能操作其他使用者資料")
