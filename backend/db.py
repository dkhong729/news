from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
import secrets
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .config import get_settings

settings = get_settings()


def get_conn():
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            schema_path = Path(__file__).resolve().parent / "sql" / "schema.sql"
            schema_sql = schema_path.read_text(encoding="utf-8").lstrip("\ufeff")
            _execute_sql_script(cur, schema_sql)
        conn.commit()


def _execute_sql_script(cur, sql: str) -> None:
    statement: List[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        statement.append(line)
        if ";" in line:
            joined = "\n".join(statement).strip()
            if joined:
                for chunk in joined.split(";"):
                    chunk = chunk.strip()
                    if chunk:
                        cur.execute(chunk)
            statement = []


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=_json_default)


def _to_jsonb(value: Any) -> Json:
    return Json(value, dumps=_json_dumps)


def _adapt_params(item: Dict[str, Any]) -> Dict[str, Any]:
    adapted: Dict[str, Any] = {}
    for k, v in item.items():
        if isinstance(v, dict):
            adapted[k] = _to_jsonb(v)
        elif isinstance(v, list) and any(isinstance(x, dict) for x in v):
            adapted[k] = _to_jsonb(v)
        else:
            adapted[k] = v
    return adapted


# ---- Raw / normalized / score ----

def upsert_raw_item(item: Dict[str, Any]) -> int:
    sql = """
    INSERT INTO raw_items (source_id, source_type, item_kind, external_id, url, title, content, author, published_at, content_hash, raw_meta)
    VALUES (%(source_id)s, %(source_type)s, %(item_kind)s, %(external_id)s, %(url)s, %(title)s, %(content)s, %(author)s, %(published_at)s, %(content_hash)s, %(raw_meta)s)
    ON CONFLICT (url) DO UPDATE SET
      source_type = EXCLUDED.source_type,
      item_kind = EXCLUDED.item_kind,
      external_id = EXCLUDED.external_id,
      title = EXCLUDED.title,
      content = EXCLUDED.content,
      author = EXCLUDED.author,
      published_at = EXCLUDED.published_at,
      content_hash = EXCLUDED.content_hash,
      raw_meta = EXCLUDED.raw_meta,
      fetched_at = NOW()
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(item))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def upsert_normalized_item(item: Dict[str, Any]) -> int:
    sql = """
    INSERT INTO normalized_items (raw_id, title, summary, why_it_matters, category, content_type, tags, language, entities)
    VALUES (%(raw_id)s, %(title)s, %(summary)s, %(why_it_matters)s, %(category)s, %(content_type)s, %(tags)s, %(language)s, %(entities)s)
    ON CONFLICT (raw_id) DO UPDATE SET
      title = EXCLUDED.title,
      summary = EXCLUDED.summary,
      why_it_matters = EXCLUDED.why_it_matters,
      category = EXCLUDED.category,
      content_type = EXCLUDED.content_type,
      tags = EXCLUDED.tags,
      language = EXCLUDED.language,
      entities = EXCLUDED.entities,
      updated_at = NOW()
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(item))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def _ensure_scores_schema(cur) -> None:
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS freshness_score REAL NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS authority_score REAL NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS signal_score REAL NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS diversity_penalty REAL NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS final_score REAL NOT NULL DEFAULT 0;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS scoring_reason TEXT;")
    cur.execute("ALTER TABLE IF EXISTS scores ADD COLUMN IF NOT EXISTS scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW();")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_scores_item_id_unique ON scores(item_id);")


def upsert_score(item: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO scores (item_id, freshness_score, authority_score, signal_score, diversity_penalty, final_score, scoring_reason)
    VALUES (%(item_id)s, %(freshness_score)s, %(authority_score)s, %(signal_score)s, %(diversity_penalty)s, %(final_score)s, %(scoring_reason)s)
    ON CONFLICT (item_id) DO UPDATE SET
      freshness_score = EXCLUDED.freshness_score,
      authority_score = EXCLUDED.authority_score,
      signal_score = EXCLUDED.signal_score,
      diversity_penalty = EXCLUDED.diversity_penalty,
      final_score = EXCLUDED.final_score,
      scoring_reason = EXCLUDED.scoring_reason,
      scored_at = NOW();
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(sql, _adapt_params(item))
            except (psycopg.errors.UndefinedColumn, psycopg.errors.InvalidColumnReference):
                _ensure_scores_schema(cur)
                cur.execute(sql, _adapt_params(item))
        conn.commit()


# ---- Events ----

def upsert_event(item: Dict[str, Any]) -> None:
    sql = """
    INSERT INTO events (title, description, location, start_at, end_at, url, organizer, source_type, source_domain, region, tags, score)
    VALUES (%(title)s, %(description)s, %(location)s, %(start_at)s, %(end_at)s, %(url)s, %(organizer)s, %(source_type)s, %(source_domain)s, %(region)s, %(tags)s, %(score)s)
    ON CONFLICT (url) DO UPDATE SET
      title = EXCLUDED.title,
      description = EXCLUDED.description,
      location = EXCLUDED.location,
      start_at = EXCLUDED.start_at,
      end_at = EXCLUDED.end_at,
      organizer = EXCLUDED.organizer,
      source_type = EXCLUDED.source_type,
      source_domain = EXCLUDED.source_domain,
      region = EXCLUDED.region,
      tags = EXCLUDED.tags,
      score = EXCLUDED.score,
      updated_at = NOW();
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(item))
        conn.commit()


def get_top_events_by_region(region: str, limit: int = 10, future_days: int = 30) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, title, description, location, start_at, end_at, url, organizer, source_type, source_domain, region, tags, score
    FROM events
    WHERE region = %s
      AND start_at IS NOT NULL
      AND start_at >= NOW()
      AND start_at < NOW() + (%s * INTERVAL '1 day')
    ORDER BY score DESC NULLS LAST, start_at ASC
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (region, future_days, limit))
            rows = cur.fetchall()
    return rows


def list_events(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, title, description, location, start_at, end_at, url, organizer, source_type, source_domain, region, tags, score, created_at, updated_at
    FROM events
    ORDER BY start_at NULLS LAST, updated_at DESC
    LIMIT %s OFFSET %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit, offset))
            return cur.fetchall()


def update_event(event_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"title", "description", "location", "start_at", "end_at", "url", "organizer", "region", "tags", "score"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_event_by_id(event_id)

    set_clause = ", ".join([f"{k} = %({k})s" for k in updates.keys()]) + ", updated_at = NOW()"
    sql = f"UPDATE events SET {set_clause} WHERE id = %(id)s RETURNING *;"
    params = {**updates, "id": event_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(params))
            row = cur.fetchone()
        conn.commit()
    return row


def list_non_zh_events(limit: int = 200) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, title, description, url, organizer, source_type, source_domain, start_at, score
    FROM events
    WHERE title ~ '[A-Za-z]{4,}'
       OR COALESCE(description, '') ~ '[A-Za-z]{8,}'
    ORDER BY updated_at DESC
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall()


def delete_event(event_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = %s;", (event_id,))
        conn.commit()


def get_event_by_id(event_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE id = %s;", (event_id,))
            return cur.fetchone()


# ---- Insights CRUD ----

def list_insights(limit: int = 100, offset: int = 0, content_type: Optional[str] = None) -> List[Dict[str, Any]]:
    where = ""
    params: List[Any] = []
    if content_type:
        where = "WHERE n.content_type = %s"
        params.append(content_type)

    sql = f"""
    SELECT n.id, n.raw_id, n.title, n.summary, n.why_it_matters, n.category, n.content_type, n.tags, n.language,
           s.final_score, s.scoring_reason, r.url, r.source_type, r.item_kind, r.published_at, n.updated_at
    FROM normalized_items n
    LEFT JOIN scores s ON s.item_id = n.id
    JOIN raw_items r ON r.id = n.raw_id
    {where}
    ORDER BY s.final_score DESC NULLS LAST, n.updated_at DESC
    LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def update_insight(item_id: int, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {"title", "summary", "why_it_matters", "category", "content_type", "tags", "language"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_insight_by_id(item_id)

    set_clause = ", ".join([f"{k} = %({k})s" for k in updates.keys()]) + ", updated_at = NOW()"
    sql = f"UPDATE normalized_items SET {set_clause} WHERE id = %(id)s RETURNING *;"
    params = {**updates, "id": item_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(params))
            row = cur.fetchone()
        conn.commit()
    return row


def list_non_zh_insights(limit: int = 200) -> List[Dict[str, Any]]:
    sql = """
    SELECT n.id, n.title, n.summary, n.why_it_matters, r.url, r.source_type
    FROM normalized_items n
    JOIN raw_items r ON r.id = n.raw_id
    WHERE n.title ~ '[A-Za-z]{4,}'
       OR COALESCE(n.summary, '') ~ '[A-Za-z]{8,}'
       OR n.language <> 'zh-TW'
    ORDER BY n.updated_at DESC
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return cur.fetchall()


def delete_insight(item_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM normalized_items WHERE id = %s;", (item_id,))
        conn.commit()


def get_insight_by_id(item_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM normalized_items WHERE id = %s;", (item_id,))
            return cur.fetchone()


# ---- Query for frontend ----

def get_top_items_for_role(role: str, limit: int = 10, lookback_days: int = 7) -> List[Dict[str, Any]]:
    category = "ai_tech" if role == "tech" else "product_biz"
    vc_order = """
    CASE WHEN LOWER(COALESCE(n.title,'') || ' ' || COALESCE(n.summary,'')) ~ '(funding|series|seed|demo day|創投|募資|加速器|accelerator)'
         THEN 1 ELSE 0 END
    """
    sql = """
    SELECT n.id, n.title, n.summary, n.why_it_matters, n.category, n.content_type, n.tags,
           s.final_score, s.scoring_reason, r.url, r.source_type, r.published_at
    FROM normalized_items n
    JOIN scores s ON s.item_id = n.id
    JOIN raw_items r ON r.id = n.raw_id
    WHERE n.category = %s
      AND COALESCE(r.published_at, r.fetched_at) >= NOW() - (%s * INTERVAL '1 day')
    ORDER BY
      CASE WHEN %s = 'vc' THEN """ + vc_order + """ ELSE 0 END DESC,
      s.final_score DESC NULLS LAST
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (category, lookback_days, role, limit))
            rows = cur.fetchall()
    return rows


def get_top_insights_balanced(limit: int = 10, per_source: int = 3, role: str = "tech", lookback_days: int = 7) -> List[Dict[str, Any]]:
    category = "ai_tech" if role == "tech" else "product_biz"
    vc_order = """
    CASE WHEN LOWER(COALESCE(n.title,'') || ' ' || COALESCE(n.summary,'')) ~ '(funding|series|seed|demo day|創投|募資|加速器|accelerator)'
         THEN 1 ELSE 0 END
    """
    sql = """
    WITH ranked AS (
      SELECT n.id, n.title, n.summary, n.why_it_matters, n.content_type, n.tags,
             s.final_score, s.scoring_reason, r.url, r.source_type, r.published_at,
             CASE WHEN %s = 'vc' THEN """ + vc_order + """ ELSE 0 END AS vc_signal,
             ROW_NUMBER() OVER (PARTITION BY r.source_type ORDER BY s.final_score DESC NULLS LAST) AS source_rank
      FROM normalized_items n
      JOIN scores s ON s.item_id = n.id
      JOIN raw_items r ON r.id = n.raw_id
      WHERE n.category = %s
        AND COALESCE(r.published_at, r.fetched_at) >= NOW() - (%s * INTERVAL '1 day')
    )
    SELECT *
    FROM ranked
    WHERE source_rank <= %s
    ORDER BY vc_signal DESC, final_score DESC NULLS LAST
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (role, category, lookback_days, per_source, limit))
            rows = cur.fetchall()
    return rows


def get_events_next_month(limit: int = 50, future_days: int = 30) -> List[Dict[str, Any]]:
    sql = """
    SELECT id, title, description, location, start_at, end_at, url, organizer, source_type, source_domain, region, tags, score
    FROM events
    WHERE start_at >= NOW() AND start_at < NOW() + (%s * INTERVAL '1 day')
    ORDER BY start_at ASC, score DESC NULLS LAST
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (future_days, limit))
            rows = cur.fetchall()
    return rows


# ---- Users / auth ----

def create_or_update_user(
    email: str,
    role: str = "tech",
    display_name: Optional[str] = None,
    is_email_verified: bool = True,
    is_email_valid: bool = True,
    is_active: bool = True,
    password_hash: Optional[str] = None,
) -> Dict[str, Any]:
    sql = """
    INSERT INTO users (email, role, display_name, is_email_verified, is_email_valid, is_active, password_hash, last_login_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    ON CONFLICT (email) DO UPDATE SET
      role = EXCLUDED.role,
      display_name = COALESCE(EXCLUDED.display_name, users.display_name),
      is_email_verified = EXCLUDED.is_email_verified,
      is_email_valid = EXCLUDED.is_email_valid,
      is_active = EXCLUDED.is_active,
      password_hash = COALESCE(EXCLUDED.password_hash, users.password_hash),
      last_login_at = NOW(),
      updated_at = NOW()
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    email,
                    role,
                    display_name,
                    is_email_verified,
                    is_email_valid,
                    is_active,
                    password_hash,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row:
        try:
            sync_user_role(int(row["id"]), role)
        except Exception:
            pass
    return row


def upsert_user_identity(user_id: int, provider: str, provider_sub: str, email: str) -> None:
    sql = """
    INSERT INTO user_identities (user_id, provider, provider_sub, email)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (provider, provider_sub) DO UPDATE SET
      user_id = EXCLUDED.user_id,
      email = EXCLUDED.email;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, provider, provider_sub, email))
        conn.commit()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email = %s;", (email,))
            return cur.fetchone()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s;", (user_id,))
            return cur.fetchone()


def bootstrap_admin_user(email: str) -> Dict[str, Any]:
    user = create_or_update_user(
        email=email.lower().strip(),
        role="admin",
        is_email_verified=True,
        is_email_valid=True,
        is_active=True,
    )
    sync_user_role(int(user["id"]), "admin")
    return user


def set_user_email_verified(user_id: int, verified: bool = True) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_email_verified = %s, updated_at = NOW() WHERE id = %s;",
                (verified, user_id),
            )
        conn.commit()


def set_user_daily_subscription(user_id: int, enabled: bool, role: str = "tech") -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_preferences (user_id, subscribe_daily)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET subscribe_daily = EXCLUDED.subscribe_daily;
                """,
                (user_id, enabled),
            )
            cur.execute(
                """
                INSERT INTO subscriptions (user_id, plan, status)
                VALUES (%s, 'free', %s)
                ON CONFLICT (user_id) DO UPDATE SET status = EXCLUDED.status;
                """,
                (user_id, "active" if enabled else "inactive"),
            )
            cur.execute(
                "UPDATE users SET role = CASE WHEN role = 'admin' THEN role ELSE %s END, updated_at = NOW() WHERE id = %s;",
                (role, user_id),
            )
        conn.commit()
    current_user = get_user_by_id(user_id)
    if current_user and current_user.get("role") == "admin":
        sync_user_role(user_id, "admin")
    else:
        sync_user_role(user_id, role)


def sync_user_role(user_id: int, role_code: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM roles WHERE code = %s;", (role_code,))
            role_row = cur.fetchone()
            if not role_row:
                return
            role_id = int(role_row["id"])
            cur.execute("DELETE FROM user_roles WHERE user_id = %s;", (user_id,))
            cur.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (user_id, role_id),
            )
        conn.commit()


def get_user_permissions(user_id: int, fallback_role: Optional[str] = None) -> List[str]:
    sql = """
    SELECT DISTINCT p.code
    FROM user_roles ur
    JOIN role_permissions rp ON rp.role_id = ur.role_id
    JOIN permissions p ON p.id = rp.permission_id
    WHERE ur.user_id = %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()

    perms = [str(row["code"]) for row in rows] if rows else []
    if perms:
        return sorted(set(perms))

    role_to_perms = {
        "vc": {"read_feed", "manage_subscription", "vc_scout_run", "vc_dd_run"},
        "biz": {"read_feed", "manage_subscription", "vc_scout_run", "vc_dd_run", "grad_dd_run"},
        "tech": {"read_feed", "manage_subscription", "vc_scout_run", "vc_dd_run", "grad_dd_run"},
        "admin": {
            "read_feed",
            "manage_subscription",
            "vc_scout_run",
            "vc_dd_run",
            "grad_dd_run",
            "pipeline_run",
            "admin_read",
            "admin_write",
        },
    }
    if fallback_role:
        return sorted(role_to_perms.get(fallback_role, {"read_feed", "manage_subscription"}))
    return ["read_feed", "manage_subscription"]


def user_has_permission(user_id: int, permission_code: str, fallback_role: Optional[str] = None) -> bool:
    return permission_code in set(get_user_permissions(user_id, fallback_role=fallback_role))


def list_daily_subscribers() -> List[Dict[str, Any]]:
    sql = """
    SELECT u.id, u.email, u.role, u.timezone
    FROM users u
    JOIN user_preferences p ON p.user_id = u.id
    LEFT JOIN subscriptions s ON s.user_id = u.id
    WHERE p.subscribe_daily = TRUE
      AND COALESCE(s.status, 'active') = 'active'
      AND u.is_active = TRUE
      AND u.is_email_valid = TRUE
      AND u.is_email_verified = TRUE;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def was_daily_digest_sent_on_date(user_id: int, target_date: date, timezone_name: str = "Asia/Taipei") -> bool:
    sql = """
    SELECT 1
    FROM email_delivery_logs
    WHERE user_id = %s
      AND detail = 'daily_digest'
      AND status = 'sent'
      AND (created_at AT TIME ZONE %s)::date = %s
    LIMIT 1;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, timezone_name, target_date))
            row = cur.fetchone()
            return bool(row)


def list_subscribers(limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
    sql = """
    SELECT
      u.id AS user_id,
      u.email,
      u.display_name,
      u.role,
      u.is_email_verified,
      u.is_email_valid,
      u.is_active,
      COALESCE(p.subscribe_daily, FALSE) AS subscribe_daily,
      COALESCE(s.status, 'inactive') AS subscription_status,
      u.last_login_at,
      u.created_at
    FROM users u
    LEFT JOIN user_preferences p ON p.user_id = u.id
    LEFT JOIN subscriptions s ON s.user_id = u.id
    ORDER BY u.created_at DESC
    LIMIT %s OFFSET %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit, offset))
            return cur.fetchall()


def update_subscriber(
    user_id: int,
    subscribe_daily: Optional[bool] = None,
    role: Optional[str] = None,
    is_email_valid: Optional[bool] = None,
    is_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if subscribe_daily is not None:
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, subscribe_daily)
                    VALUES (%s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET subscribe_daily = EXCLUDED.subscribe_daily;
                    """,
                    (user_id, subscribe_daily),
                )
            if role:
                cur.execute(
                    "UPDATE users SET role = %s, updated_at = NOW() WHERE id = %s;",
                    (role, user_id),
                )
                sync_user_role(user_id, role)
            if is_email_valid is not None:
                cur.execute(
                    "UPDATE users SET is_email_valid = %s, updated_at = NOW() WHERE id = %s;",
                    (is_email_valid, user_id),
                )
            if is_active is not None:
                cur.execute(
                    "UPDATE users SET is_active = %s, updated_at = NOW() WHERE id = %s;",
                    (is_active, user_id),
                )
            cur.execute(
                """
                SELECT
                  u.id AS user_id,
                  u.email,
                  u.display_name,
                  u.role,
                  u.is_email_verified,
                  u.is_email_valid,
                  u.is_active,
                  COALESCE(p.subscribe_daily, FALSE) AS subscribe_daily,
                  COALESCE(s.status, 'inactive') AS subscription_status
                FROM users u
                LEFT JOIN user_preferences p ON p.user_id = u.id
                LEFT JOIN subscriptions s ON s.user_id = u.id
                WHERE u.id = %s;
                """,
                (user_id,),
            )
            row = cur.fetchone()
        conn.commit()
    return row


def add_user_source(user_id: int, url: str, source_type: str = "custom") -> int:
    sql = """
    INSERT INTO user_sources (user_id, url, source_type)
    VALUES (%s, %s, %s)
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, url, source_type))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def list_user_sources(user_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_sources WHERE user_id = %s AND active = TRUE;", (user_id,))
            return cur.fetchall()


def list_all_active_user_sources() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, user_id, url, source_type FROM user_sources WHERE active = TRUE ORDER BY id DESC;")
            return cur.fetchall()


def log_auth_attempt(ip: Optional[str], action: str, email: Optional[str], success: bool) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auth_audit_logs (ip, action, email, success) VALUES (%s, %s, %s, %s);",
                (ip, action, email, success),
            )
        conn.commit()


def count_recent_auth_attempts(
    action: str,
    ip: Optional[str] = None,
    email: Optional[str] = None,
    minutes: int = 15,
) -> int:
    conditions = ["action = %s", "created_at >= NOW() - (%s || ' minutes')::interval"]
    params: List[Any] = [action, minutes]
    if ip:
        conditions.append("ip = %s")
        params.append(ip)
    if email:
        conditions.append("email = %s")
        params.append(email)
    where_clause = " AND ".join(conditions)
    sql = f"SELECT COUNT(*) AS c FROM auth_audit_logs WHERE {where_clause};"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
    return int(row["c"])


def create_unsubscribe_token(user_id: int, ttl_days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO unsubscribe_tokens (token, user_id, expires_at)
                VALUES (%s, %s, NOW() + (%s * INTERVAL '1 day'));
                """,
                (token, user_id, ttl_days),
            )
        conn.commit()
    return token


def consume_unsubscribe_token(token: str) -> Optional[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE unsubscribe_tokens
                SET used_at = NOW()
                WHERE token = %s
                  AND used_at IS NULL
                  AND expires_at > NOW()
                RETURNING user_id;
                """,
                (token,),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["user_id"]) if row else None


def mark_user_email_invalid(email: str, reason: str = "bounce") -> Optional[int]:
    email_norm = (email or "").lower().strip()
    if not email_norm:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET is_email_valid = FALSE, updated_at = NOW()
                WHERE email = %s
                RETURNING id;
                """,
                (email_norm,),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, subscribe_daily)
                    VALUES (%s, FALSE)
                    ON CONFLICT (user_id) DO UPDATE SET subscribe_daily = FALSE;
                    """,
                    (row["id"],),
                )
                cur.execute(
                    """
                    INSERT INTO email_delivery_logs (user_id, email, provider, subject, status, provider_event, detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (row["id"], email_norm, "webhook", "", "failed", reason, "email marked invalid"),
                )
        conn.commit()
    return int(row["id"]) if row else None


def log_email_delivery(
    email: str,
    subject: str,
    status: str,
    provider: str,
    provider_message_id: Optional[str] = None,
    response_code: Optional[int] = None,
    detail: Optional[str] = None,
    provider_event: Optional[str] = None,
    user_id: Optional[int] = None,
) -> int:
    sql = """
    INSERT INTO email_delivery_logs (
      user_id, email, provider, subject, status, provider_message_id, provider_event, response_code, detail
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (user_id, email, provider, subject, status, provider_message_id, provider_event, response_code, detail),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def create_pipeline_run(trigger_source: str = "manual") -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_runs (status, trigger_source) VALUES (%s, %s) RETURNING id;",
                ("running", trigger_source),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def finish_pipeline_run(run_id: int, status: str, result_json: Optional[Dict[str, Any]] = None, error_message: Optional[str] = None) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pipeline_runs
                SET status = %s,
                    finished_at = NOW(),
                    duration_ms = GREATEST(0, FLOOR(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::INT),
                    result_json = %s,
                    error_message = %s
                WHERE id = %s;
                """,
                (status, _to_jsonb(result_json or {}), error_message, run_id),
            )
        conn.commit()


def record_source_health(source_key: str, success: bool) -> None:
    sql = """
    INSERT INTO source_health (source_key, success_count, failure_count, consecutive_failures, last_success_at, last_failure_at, updated_at)
    VALUES (
      %s,
      CASE WHEN %s THEN 1 ELSE 0 END,
      CASE WHEN %s THEN 0 ELSE 1 END,
      CASE WHEN %s THEN 0 ELSE 1 END,
      CASE WHEN %s THEN NOW() ELSE NULL END,
      CASE WHEN %s THEN NULL ELSE NOW() END,
      NOW()
    )
    ON CONFLICT (source_key) DO UPDATE SET
      success_count = source_health.success_count + CASE WHEN EXCLUDED.success_count > 0 THEN 1 ELSE 0 END,
      failure_count = source_health.failure_count + CASE WHEN EXCLUDED.failure_count > 0 THEN 1 ELSE 0 END,
      consecutive_failures = CASE
        WHEN EXCLUDED.success_count > 0 THEN 0
        ELSE source_health.consecutive_failures + 1
      END,
      last_success_at = CASE WHEN EXCLUDED.success_count > 0 THEN NOW() ELSE source_health.last_success_at END,
      last_failure_at = CASE WHEN EXCLUDED.failure_count > 0 THEN NOW() ELSE source_health.last_failure_at END,
      updated_at = NOW();
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (source_key, success, success, success, success, success))
        conn.commit()


def get_source_health(source_key: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM source_health WHERE source_key = %s;", (source_key,))
            return cur.fetchone()


def upsert_source_cache(url: str, status_code: int, body: str, source: Optional[str] = None) -> None:
    sql = """
    INSERT INTO source_cache (url, status_code, body, fetched_at, source)
    VALUES (%s, %s, %s, NOW(), %s)
    ON CONFLICT (url) DO UPDATE SET
      status_code = EXCLUDED.status_code,
      body = EXCLUDED.body,
      source = EXCLUDED.source,
      fetched_at = NOW();
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (url, status_code, body, source))
        conn.commit()


def get_source_cache(url: str, max_age_hours: int = 24) -> Optional[Dict[str, Any]]:
    sql = """
    SELECT url, status_code, body, fetched_at, source
    FROM source_cache
    WHERE url = %s
      AND fetched_at >= NOW() - (%s * INTERVAL '1 hour')
    LIMIT 1;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (url, max_age_hours))
            return cur.fetchone()


def prune_stale_data(
    paper_days: int = 14,
    post_days: int = 7,
    web_past_days: int = 7,
    web_future_days: int = 7,
    event_future_days: int = 60,
) -> Dict[str, int]:
    deleted = {"raw_items": 0, "events": 0}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM raw_items
                WHERE
                  (item_kind = 'paper' AND COALESCE(published_at, fetched_at) < NOW() - (%s * INTERVAL '1 day'))
                  OR (item_kind = 'post' AND COALESCE(published_at, fetched_at) < NOW() - (%s * INTERVAL '1 day'))
                  OR (
                      item_kind = 'web'
                      AND (
                        COALESCE(published_at, fetched_at) < NOW() - (%s * INTERVAL '1 day')
                        OR COALESCE(published_at, fetched_at) > NOW() + (%s * INTERVAL '1 day')
                      )
                  );
                """,
                (paper_days, post_days, web_past_days, web_future_days),
            )
            deleted["raw_items"] = cur.rowcount or 0
            cur.execute(
                """
                DELETE FROM events
                WHERE start_at IS NULL
                  OR start_at < NOW()
                  OR start_at > NOW() + (%s * INTERVAL '1 day');
                """,
                (event_future_days,),
            )
            deleted["events"] = cur.rowcount or 0
        conn.commit()
    return deleted


def purge_listing_events() -> int:
    sql = """
    DELETE FROM events
    WHERE COALESCE(url, '') ~* '(seminar_list|/list|/calendar|/category|/tag/|/search)';
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            count = cur.rowcount or 0
        conn.commit()
    return count


def cleanup_low_quality_content(
    min_event_score: float = 4.5,
    min_insight_score: float = 4.0,
    max_title_len: int = 220,
) -> Dict[str, int]:
    """
    定期清理低品質/異常資料，避免資料庫長期堆積：
    - 過長或疑似亂碼標題
    - 低分且不相關事件
    - 低分且明顯異常的新知
    - 孤兒 raw_items（已無 normalized_items）
    """
    stats = {
        "events_deleted_low_quality": 0,
        "insights_deleted_low_quality": 0,
        "raw_items_deleted_orphan": 0,
    }
    with get_conn() as conn:
        with conn.cursor() as cur:
            # 事件：過長標題、明顯亂碼、低分且缺乏活動/AI 新創關鍵字
            cur.execute(
                """
                DELETE FROM events
                WHERE
                  char_length(COALESCE(title, '')) > %s
                  OR COALESCE(title, '') ~ '[�]'
                  OR COALESCE(description, '') ~ '[�]'
                  OR lower(COALESCE(title,'')) LIKE '%%Ã%%'
                  OR (
                    COALESCE(score, 0) < %s
                    AND lower(COALESCE(title,'') || ' ' || COALESCE(description,'')) !~ 
                      '(ai|人工智慧|新創|創業|創投|startup|demo day|accelerator|論壇|研討|conference|summit|workshop|expo|展覽)'
                  );
                """,
                (max_title_len, min_event_score),
            )
            stats["events_deleted_low_quality"] = cur.rowcount or 0

            # 新知：超長標題、含程式碼/回覆型內容、疑似亂碼，且分數偏低
            cur.execute(
                """
                DELETE FROM normalized_items n
                USING scores s
                WHERE s.item_id = n.id
                  AND s.final_score < %s
                  AND (
                    char_length(COALESCE(n.title, '')) > %s
                    OR COALESCE(n.title, '') ~ '[�]'
                    OR COALESCE(n.summary, '') ~ '[�]'
                    OR lower(COALESCE(n.title,'')) LIKE '%%Ã%%'
                    OR COALESCE(n.title,'') ~ '```'
                    OR COALESCE(n.title,'') ~ E'[\\r\\n]'
                  );
                """,
                (min_insight_score, max_title_len + 40),
            )
            stats["insights_deleted_low_quality"] = cur.rowcount or 0

            # 刪除無 normalized 對應且超過保留期的 raw_items（留少量近期資料供追查）
            cur.execute(
                """
                DELETE FROM raw_items r
                WHERE NOT EXISTS (SELECT 1 FROM normalized_items n WHERE n.raw_id = r.id)
                  AND NOT EXISTS (SELECT 1 FROM events e WHERE e.url = r.url)
                  AND COALESCE(r.published_at, r.fetched_at) < NOW() - INTERVAL '14 days';
                """
            )
            stats["raw_items_deleted_orphan"] = cur.rowcount or 0

        conn.commit()
    return stats


def content_quality_audit(limit: int = 20, max_title_len: int = 220) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE char_length(COALESCE(title,'')) > %s;
                """,
                (max_title_len,),
            )
            report["event_title_too_long"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE COALESCE(title,'') ~ '[�]' OR lower(COALESCE(title,'')) LIKE '%%Ã%%';
                """
            )
            report["event_title_mojibake"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE char_length(COALESCE(title,'')) > %s OR COALESCE(title,'') ~ '[�]' OR lower(COALESCE(title,'')) LIKE '%%Ã%%';
                """,
                (max_title_len,),
            )
            report["event_title_issues"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM normalized_items
                WHERE char_length(COALESCE(title,'')) > %s;
                """,
                (max_title_len + 40,),
            )
            report["insight_title_too_long"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM normalized_items
                WHERE COALESCE(title,'') ~ '[�]' OR lower(COALESCE(title,'')) LIKE '%%Ã%%';
                """
            )
            report["insight_title_mojibake"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM normalized_items
                WHERE char_length(COALESCE(title,'')) > %s OR COALESCE(title,'') ~ '[�]' OR lower(COALESCE(title,'')) LIKE '%%Ã%%';
                """,
                (max_title_len + 40,),
            )
            report["insight_title_issues"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM events
                WHERE COALESCE(url, '') ~* '(seminar_list|/list|/calendar|/category|/tag/|/search)';
                """
            )
            report["listing_event_count"] = int((cur.fetchone() or {}).get("cnt") or 0)

            cur.execute(
                """
                SELECT id, title, url, score
                FROM events
                WHERE char_length(COALESCE(title,'')) > %s OR COALESCE(title,'') ~ '[�]' OR lower(COALESCE(title,'')) LIKE '%%Ã%%'
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s;
                """,
                (max_title_len, limit),
            )
            report["event_samples"] = cur.fetchall()

            cur.execute(
                """
                SELECT n.id, n.title, r.url, s.final_score
                FROM normalized_items n
                LEFT JOIN raw_items r ON r.id = n.raw_id
                LEFT JOIN scores s ON s.item_id = n.id
                WHERE char_length(COALESCE(n.title,'')) > %s OR COALESCE(n.title,'') ~ '[�]' OR lower(COALESCE(n.title,'')) LIKE '%%Ã%%'
                ORDER BY n.updated_at DESC
                LIMIT %s;
                """,
                (max_title_len + 40, limit),
            )
            report["insight_samples"] = cur.fetchall()

            cur.execute(
                """
                SELECT id, title, url, score
                FROM events
                WHERE COALESCE(url, '') ~* '(seminar_list|/list|/calendar|/category|/tag/|/search)'
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %s;
                """,
                (limit,),
            )
            report["listing_event_samples"] = cur.fetchall()
    return report


def upsert_gov_resource_record(item: Dict[str, Any]) -> int:
    sql = """
    INSERT INTO gov_resource_records (
      record_type, source_category, program_name, event_name, company_name, organization_name, year,
      award_name, subsidy_name, date_text, booth_no, url, source_url, source_domain, region, score, raw_meta
    )
    VALUES (
      %(record_type)s, %(source_category)s, %(program_name)s, %(event_name)s, %(company_name)s, %(organization_name)s, %(year)s,
      %(award_name)s, %(subsidy_name)s, %(date_text)s, %(booth_no)s, %(url)s, %(source_url)s, %(source_domain)s, %(region)s, %(score)s, %(raw_meta)s
    )
    ON CONFLICT (record_type, source_category, program_name, event_name, company_name, organization_name, year, url, source_url)
    DO UPDATE SET
      source_domain = EXCLUDED.source_domain,
      region = EXCLUDED.region,
      score = EXCLUDED.score,
      raw_meta = EXCLUDED.raw_meta,
      updated_at = NOW()
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(item))
            row = cur.fetchone()
        conn.commit()
    return int((row or {}).get("id") or 0)


def list_gov_resource_records(
    limit: int = 200,
    offset: int = 0,
    record_type: Optional[str] = None,
    source_category: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> List[Dict[str, Any]]:
    where_parts: List[str] = []
    params: List[Any] = []
    if record_type:
        where_parts.append("record_type = %s")
        params.append(record_type)
    if source_category:
        where_parts.append("source_category = %s")
        params.append(source_category)
    if year_from is not None:
        where_parts.append("(year IS NULL OR year >= %s)")
        params.append(year_from)
    if year_to is not None:
        where_parts.append("(year IS NULL OR year <= %s)")
        params.append(year_to)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    sql = f"""
    SELECT id, record_type, source_category, program_name, event_name, company_name, organization_name, year,
           award_name, subsidy_name, date_text, booth_no, url, source_url, source_domain, region, score, raw_meta,
           created_at, updated_at
    FROM gov_resource_records
    {where_sql}
    ORDER BY year DESC NULLS LAST, score DESC NULLS LAST, updated_at DESC
    LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def count_gov_resource_records() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM gov_resource_records;")
            row = cur.fetchone()
            return int((row or {}).get("cnt") or 0)


def create_oauth_state(state: str, ip: Optional[str], ttl_minutes: int = 10) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oauth_states (state, ip, expires_at)
                VALUES (%s, %s, NOW() + (%s || ' minutes')::interval)
                ON CONFLICT (state) DO UPDATE SET
                  ip = EXCLUDED.ip,
                  expires_at = EXCLUDED.expires_at,
                  used_at = NULL;
                """,
                (state, ip, ttl_minutes),
            )
        conn.commit()


def consume_oauth_state(state: str, ip: Optional[str]) -> bool:
    conditions = "state = %s AND used_at IS NULL AND expires_at > NOW()"
    params: List[Any] = [state]
    if ip:
        conditions += " AND (ip IS NULL OR ip = %s)"
        params.append(ip)
    sql = f"UPDATE oauth_states SET used_at = NOW() WHERE {conditions} RETURNING state;"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        conn.commit()
    return bool(row)


# ---- VC scouting ----

def upsert_vc_profile(
    user_id: int,
    firm_name: str,
    thesis: str,
    preferred_stages: List[str],
    preferred_sectors: List[str],
    preferred_geo: str = "global",
) -> Dict[str, Any]:
    sql = """
    INSERT INTO vc_profiles (user_id, firm_name, thesis, preferred_stages, preferred_sectors, preferred_geo)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (user_id) DO UPDATE SET
      firm_name = EXCLUDED.firm_name,
      thesis = EXCLUDED.thesis,
      preferred_stages = EXCLUDED.preferred_stages,
      preferred_sectors = EXCLUDED.preferred_sectors,
      preferred_geo = EXCLUDED.preferred_geo,
      updated_at = NOW()
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, firm_name, thesis, preferred_stages, preferred_sectors, preferred_geo))
            row = cur.fetchone()
        conn.commit()
    return row


def get_vc_profile(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM vc_profiles WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


def get_vc_candidate(candidate_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM vc_candidates WHERE id = %s;", (candidate_id,))
            return cur.fetchone()


def clear_vc_candidates(profile_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vc_candidates WHERE profile_id = %s;", (profile_id,))
        conn.commit()


def upsert_vc_candidate(profile_id: int, item: Dict[str, Any]) -> int:
    sql = """
    INSERT INTO vc_candidates (
      profile_id, name, summary, source_url, source_type, stage, sector, score, rationale, contact_email, raw_meta
    )
    VALUES (
      %(profile_id)s, %(name)s, %(summary)s, %(source_url)s, %(source_type)s, %(stage)s, %(sector)s, %(score)s, %(rationale)s, %(contact_email)s, %(raw_meta)s
    )
    ON CONFLICT (profile_id, source_url, name) DO UPDATE SET
      summary = EXCLUDED.summary,
      source_type = EXCLUDED.source_type,
      stage = EXCLUDED.stage,
      sector = EXCLUDED.sector,
      score = EXCLUDED.score,
      rationale = EXCLUDED.rationale,
      contact_email = EXCLUDED.contact_email,
      raw_meta = EXCLUDED.raw_meta,
      updated_at = NOW()
    RETURNING id;
    """
    params = {**item, "profile_id": profile_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(params))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def list_vc_candidates(profile_id: int, limit: int = 50, shortlisted_only: bool = False) -> List[Dict[str, Any]]:
    where = "WHERE profile_id = %s"
    params: List[Any] = [profile_id]
    if shortlisted_only:
        where += " AND shortlisted = TRUE"
    sql = f"""
    SELECT *
    FROM vc_candidates
    {where}
    ORDER BY score DESC, updated_at DESC
    LIMIT %s;
    """
    params.append(limit)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def mark_vc_shortlist(profile_id: int, candidate_ids: List[int]) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE vc_candidates SET shortlisted = FALSE WHERE profile_id = %s;", (profile_id,))
            if candidate_ids:
                cur.execute(
                    "UPDATE vc_candidates SET shortlisted = TRUE WHERE profile_id = %s AND id = ANY(%s);",
                    (profile_id, candidate_ids),
                )
                updated = cur.rowcount or 0
            else:
                updated = 0
        conn.commit()
    return updated


def insert_vc_outreach_log(candidate_id: int, user_id: int, subject: str, body: str, sent: bool) -> int:
    sql = """
    INSERT INTO vc_outreach_logs (candidate_id, user_id, subject, body, sent, sent_at)
    VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END)
    RETURNING id;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (candidate_id, user_id, subject, body, sent, sent))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def create_vc_meeting_request(candidate_id: int, proposed_slots: List[str]) -> Dict[str, Any]:
    sql = """
    INSERT INTO vc_meeting_requests (candidate_id, proposed_slots, status)
    VALUES (%s, %s, 'draft')
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (candidate_id, proposed_slots))
            row = cur.fetchone()
        conn.commit()
    return row


def set_candidate_outreach_status(candidate_id: int, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vc_candidates SET outreach_status = %s, updated_at = NOW() WHERE id = %s;",
                (status, candidate_id),
            )
        conn.commit()


def set_candidate_meeting_status(candidate_id: int, status: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE vc_candidates SET meeting_status = %s, updated_at = NOW() WHERE id = %s;",
                (status, candidate_id),
            )
        conn.commit()


def upsert_vc_dd_report(
    profile_id: int,
    candidate_id: int,
    title: str,
    report_json: Dict[str, Any],
    markdown: str,
    confidence: float,
) -> Dict[str, Any]:
    sql = """
    INSERT INTO vc_dd_reports (profile_id, candidate_id, title, report_json, markdown, confidence)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (profile_id, candidate_id) DO UPDATE SET
      title = EXCLUDED.title,
      report_json = EXCLUDED.report_json,
      markdown = EXCLUDED.markdown,
      confidence = EXCLUDED.confidence,
      generated_at = NOW()
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (profile_id, candidate_id, title, _to_jsonb(report_json), markdown, confidence))
            row = cur.fetchone()
        conn.commit()
    return row


def list_vc_dd_reports(profile_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    sql = """
    SELECT r.*, c.name AS candidate_name, c.source_url
    FROM vc_dd_reports r
    JOIN vc_candidates c ON c.id = r.candidate_id
    WHERE r.profile_id = %s
    ORDER BY r.generated_at DESC
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (profile_id, limit))
            return cur.fetchall()


def get_latest_vc_dd_report(profile_id: int, candidate_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    where = "WHERE r.profile_id = %s"
    params: List[Any] = [profile_id]
    if candidate_id is not None:
        where += " AND r.candidate_id = %s"
        params.append(candidate_id)
    sql = f"""
    SELECT r.*, c.name AS candidate_name, c.source_url
    FROM vc_dd_reports r
    JOIN vc_candidates c ON c.id = r.candidate_id
    {where}
    ORDER BY r.generated_at DESC
    LIMIT 1;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchone()


def find_public_signals_for_candidate(
    candidate_name: str,
    source_url: Optional[str],
    lookback_days: int = 180,
    insight_limit: int = 60,
    event_limit: int = 30,
) -> Dict[str, List[Dict[str, Any]]]:
    text = (candidate_name or "").strip().lower()
    tokens = [t for t in text.replace("-", " ").split() if len(t) >= 3][:6]
    if not tokens and text:
        tokens = [text[:50]]

    domain = ""
    if source_url:
        try:
            domain = (urlparse(source_url).netloc or "").lower()
        except Exception:
            domain = ""
    domain_like = f"%{domain}%" if domain else ""

    insight_where: List[str] = ["COALESCE(r.published_at, r.fetched_at) >= NOW() - (%s * INTERVAL '1 day')"]
    insight_params: List[Any] = [lookback_days]
    if tokens:
        token_clause = " OR ".join(
            [
                "LOWER(COALESCE(n.title, '')) LIKE %s",
                "LOWER(COALESCE(n.summary, '')) LIKE %s",
                "LOWER(COALESCE(r.url, '')) LIKE %s",
            ]
            * len(tokens)
        )
        insight_where.append(f"({token_clause})")
        for token in tokens:
            pattern = f"%{token}%"
            insight_params.extend([pattern, pattern, pattern])
    if domain_like:
        insight_where.append("LOWER(COALESCE(r.url, '')) LIKE %s")
        insight_params.append(domain_like)
    insight_where_sql = " AND ".join(insight_where)

    insights_sql = f"""
    SELECT
      n.id,
      n.title,
      n.summary,
      n.why_it_matters,
      n.content_type,
      n.category,
      r.url,
      r.source_type,
      COALESCE(r.published_at, r.fetched_at) AS published_at,
      s.final_score
    FROM normalized_items n
    JOIN raw_items r ON r.id = n.raw_id
    LEFT JOIN scores s ON s.item_id = n.id
    WHERE {insight_where_sql}
    ORDER BY COALESCE(s.final_score, 0) DESC, COALESCE(r.published_at, r.fetched_at) DESC
    LIMIT %s;
    """
    insight_params.append(insight_limit)

    event_where: List[str] = [
        "COALESCE(start_at, created_at) >= NOW() - (30 * INTERVAL '1 day')",
        "COALESCE(start_at, created_at) <= NOW() + (%s * INTERVAL '1 day')",
    ]
    event_params: List[Any] = [lookback_days]
    if tokens:
        token_clause = " OR ".join(
            [
                "LOWER(COALESCE(title, '')) LIKE %s",
                "LOWER(COALESCE(description, '')) LIKE %s",
                "LOWER(COALESCE(url, '')) LIKE %s",
            ]
            * len(tokens)
        )
        event_where.append(f"({token_clause})")
        for token in tokens:
            pattern = f"%{token}%"
            event_params.extend([pattern, pattern, pattern])
    if domain_like:
        event_where.append("LOWER(COALESCE(url, '')) LIKE %s")
        event_params.append(domain_like)
    event_where_sql = " AND ".join(event_where)
    events_sql = f"""
    SELECT
      id,
      title,
      description,
      organizer,
      url,
      source_type,
      source_domain,
      region,
      start_at,
      score
    FROM events
    WHERE {event_where_sql}
    ORDER BY COALESCE(score, 0) DESC, COALESCE(start_at, created_at) DESC
    LIMIT %s;
    """
    event_params.append(event_limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(insights_sql, tuple(insight_params))
            insights = cur.fetchall()
            cur.execute(events_sql, tuple(event_params))
            events = cur.fetchall()

    return {"insights": insights, "events": events}


def upsert_grad_dd_profile(
    user_id: int,
    resume_text: str,
    target_schools: List[str],
    interests: List[str],
    degree_target: str = "master",
) -> Dict[str, Any]:
    sql = """
    INSERT INTO grad_dd_profiles (user_id, resume_text, target_schools, interests, degree_target)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (user_id) DO UPDATE SET
      resume_text = EXCLUDED.resume_text,
      target_schools = EXCLUDED.target_schools,
      interests = EXCLUDED.interests,
      degree_target = EXCLUDED.degree_target,
      updated_at = NOW()
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, resume_text, target_schools, interests, degree_target))
            row = cur.fetchone()
        conn.commit()
    return row


def get_grad_dd_profile(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM grad_dd_profiles WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


def clear_grad_lab_candidates(profile_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM grad_lab_candidates WHERE profile_id = %s;", (profile_id,))
        conn.commit()


def upsert_grad_lab_candidate(profile_id: int, item: Dict[str, Any]) -> int:
    sql = """
    INSERT INTO grad_lab_candidates (
      profile_id, school, lab_name, lab_url, professor, score, rationale, evidence
    )
    VALUES (
      %(profile_id)s, %(school)s, %(lab_name)s, %(lab_url)s, %(professor)s, %(score)s, %(rationale)s, %(evidence)s
    )
    ON CONFLICT (profile_id, school, lab_name, lab_url) DO UPDATE SET
      professor = EXCLUDED.professor,
      score = EXCLUDED.score,
      rationale = EXCLUDED.rationale,
      evidence = EXCLUDED.evidence,
      updated_at = NOW()
    RETURNING id;
    """
    params = {**item, "profile_id": profile_id}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _adapt_params(params))
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def list_grad_lab_candidates(profile_id: int, limit: int = 50, shortlisted_only: bool = False) -> List[Dict[str, Any]]:
    where = "WHERE profile_id = %s"
    params: List[Any] = [profile_id]
    if shortlisted_only:
        where += " AND shortlisted = TRUE"
    sql = f"""
    SELECT *
    FROM grad_lab_candidates
    {where}
    ORDER BY score DESC, updated_at DESC
    LIMIT %s;
    """
    params.append(limit)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()


def mark_grad_lab_shortlist(profile_id: int, candidate_ids: List[int]) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE grad_lab_candidates SET shortlisted = FALSE WHERE profile_id = %s;", (profile_id,))
            if candidate_ids:
                cur.execute(
                    "UPDATE grad_lab_candidates SET shortlisted = TRUE WHERE profile_id = %s AND id = ANY(%s);",
                    (profile_id, candidate_ids),
                )
                updated = cur.rowcount or 0
            else:
                updated = 0
        conn.commit()
    return updated


def insert_grad_dd_report(profile_id: int, report_json: Dict[str, Any], markdown: str) -> Dict[str, Any]:
    sql = """
    INSERT INTO grad_dd_reports (profile_id, report_json, markdown)
    VALUES (%s, %s, %s)
    RETURNING *;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (profile_id, _to_jsonb(report_json), markdown))
            row = cur.fetchone()
        conn.commit()
    return row


def get_latest_grad_dd_report(profile_id: int) -> Optional[Dict[str, Any]]:
    sql = """
    SELECT *
    FROM grad_dd_reports
    WHERE profile_id = %s
    ORDER BY generated_at DESC
    LIMIT 1;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (profile_id,))
            return cur.fetchone()


def list_grad_dd_reports(profile_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    sql = """
    SELECT *
    FROM grad_dd_reports
    WHERE profile_id = %s
    ORDER BY generated_at DESC
    LIMIT %s;
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (profile_id, limit))
            return cur.fetchall()


# ---- Legacy compatibility helpers used by existing modules ----

def insert_raw_item(item: Dict[str, Any]) -> Optional[int]:
    return upsert_raw_item(item)


def insert_normalized_item(item: Dict[str, Any]) -> Optional[int]:
    return upsert_normalized_item(item)


def insert_score(item: Dict[str, Any]) -> None:
    # Backward compatibility for older score payload.
    mapped = {
        "item_id": item.get("item_id"),
        "freshness_score": float(item.get("freshness_score", item.get("value_score", 0) or 0)),
        "authority_score": float(item.get("authority_score", item.get("novelty_score", 0) or 0)),
        "signal_score": float(item.get("signal_score", item.get("relevance_score", 0) or 0)),
        "diversity_penalty": float(item.get("diversity_penalty", 0)),
        "final_score": float(item.get("final_score", 0) or 0),
        "scoring_reason": item.get("scoring_reason", ""),
    }
    upsert_score(mapped)


def create_user(email: str, role: str, password_hash: str) -> int:
    user = create_or_update_user(
        email=email,
        role=role,
        display_name=None,
        is_email_verified=False,
        password_hash=password_hash or None,
    )
    return int(user["id"])


def upsert_subscription(user_id: int, plan: str, status: str = "active") -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscriptions (user_id, plan, status)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET plan = EXCLUDED.plan, status = EXCLUDED.status
                RETURNING id;
                """,
                (user_id, plan, status),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["id"])


def get_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM subscriptions WHERE user_id = %s;", (user_id,))
            return cur.fetchone()


def create_magic_link(user_id: int, ttl_minutes: int = 30) -> str:
    token = secrets.token_urlsafe(24)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO magic_links (user_id, token, expires_at)
                VALUES (%s, %s, NOW() + (%s || ' minutes')::interval);
                """,
                (user_id, token, ttl_minutes),
            )
        conn.commit()
    return token


def consume_magic_link(token: str) -> Optional[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE magic_links
                SET used_at = NOW()
                WHERE token = %s AND used_at IS NULL AND expires_at > NOW()
                RETURNING user_id;
                """,
                (token,),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row["user_id"]) if row else None
