import os
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class EmailConfig:
    provider: str
    api_key: str
    from_email: str
    reply_to: Optional[str] = None


def _email_trust_env_proxy() -> bool:
    return os.getenv("EMAIL_TRUST_ENV_PROXY", "0") == "1"


def _email_proxy_override() -> Optional[str]:
    value = os.getenv("EMAIL_PROXY_URL", "").strip()
    return value or None



def get_email_config() -> EmailConfig:
    return EmailConfig(
        provider=os.getenv("EMAIL_PROVIDER", "sendgrid"),
        api_key=os.getenv("EMAIL_API_KEY", ""),
        from_email=os.getenv("EMAIL_FROM", "no-reply@aiinsightpulse.com"),
        reply_to=os.getenv("EMAIL_REPLY_TO", "").strip() or None,
    )



def send_email(to_email: str, subject: str, html: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Optional[str]]:
    cfg = get_email_config()
    if not cfg.api_key:
        raise RuntimeError("EMAIL_API_KEY is not set")

    if cfg.provider == "sendgrid":
        return _send_sendgrid(cfg, to_email, subject, html, headers=headers)
    if cfg.provider == "ses":
        return _send_ses(cfg, to_email, subject, html)
    if cfg.provider == "smtp":
        return _send_smtp(cfg, to_email, subject, html)
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {cfg.provider}")



def _send_sendgrid(
    cfg: EmailConfig,
    to_email: str,
    subject: str,
    html: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[str]]:
    import requests

    personalization = {"to": [{"email": to_email}]}
    payload = {
        "personalizations": [personalization],
        "from": {"email": cfg.from_email},
        "subject": subject,
        "content": [{"type": "text/html", "value": html}],
    }
    if cfg.reply_to:
        payload["reply_to"] = {"email": cfg.reply_to}
    if headers:
        payload["headers"] = headers

    session = requests.Session()
    session.trust_env = _email_trust_env_proxy()
    proxy = _email_proxy_override()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    resp = session.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
        proxies=proxies,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"SendGrid error: {resp.status_code} {resp.text}")

    message_id = resp.headers.get("x-message-id") or resp.headers.get("X-Message-Id")
    return {
        "provider": "sendgrid",
        "message_id": message_id,
        "status": str(resp.status_code),
    }



def _send_ses(cfg: EmailConfig, to_email: str, subject: str, html: str) -> Dict[str, Optional[str]]:
    raise RuntimeError("SES not implemented yet")



def _send_smtp(cfg: EmailConfig, to_email: str, subject: str, html: str) -> Dict[str, Optional[str]]:
    raise RuntimeError("SMTP not implemented yet")
