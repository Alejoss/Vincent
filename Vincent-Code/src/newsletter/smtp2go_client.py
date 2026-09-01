"""SMTP2GO API client for newsletter test and campaign sends."""

from __future__ import annotations

from typing import Any

import httpx

from .config import NewsletterConfig
from .renderer import RenderedNewsletter
from .send_result import SendResult
from .subscribers import Subscriber

SMTP2GO_API = "https://api.smtp2go.com/v3"


def _headers(config: NewsletterConfig) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Smtp2go-Api-Key": config.api_key,
    }


def _inlines(rendered: RenderedNewsletter) -> list[dict[str, str]]:
    """Convert renderer CID attachments to SMTP2GO inlines.

    HTML already uses src=\"cid:...\"; SMTP2GO matches inline filename to that CID.
    """
    inlines: list[dict[str, str]] = []
    for att in rendered.attachments or []:
        cid = str(att.get("ContentID") or "").removeprefix("cid:")
        filename = cid or str(att.get("Name") or "inline.png")
        inlines.append(
            {
                "filename": filename,
                "fileblob": str(att.get("Content") or ""),
                "mimetype": str(att.get("ContentType") or "application/octet-stream"),
            }
        )
    return inlines


def _base_payload(config: NewsletterConfig, rendered: RenderedNewsletter) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sender": config.from_address,
        "subject": rendered.subject,
        "html_body": rendered.email_html_body,
        "text_body": rendered.text_body,
        "custom_headers": [
            {"header": "X-Newsletter-Tag", "value": rendered.tag},
            {"header": "X-Newsletter-Segment", "value": rendered.segment},
        ],
    }
    if config.reply_to:
        payload["custom_headers"].append({"header": "Reply-To", "value": config.reply_to})

    inlines = _inlines(rendered)
    if inlines:
        payload["inlines"] = inlines
    return payload


def _parse_error(data: dict[str, Any] | None, fallback: str) -> str:
    if not data:
        return fallback
    err = data.get("data") if isinstance(data.get("data"), dict) else data
    if isinstance(err, dict):
        return str(err.get("error") or err.get("Message") or fallback)
    return fallback


def _response_ok(data: dict[str, Any]) -> tuple[bool, str]:
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    failed = int(body.get("failed") or 0)
    if failed:
        failures = body.get("failures") or []
        detail = failures[0] if failures else body
        return False, _parse_error({"data": detail} if not isinstance(detail, dict) else {"data": detail}, "Envío fallido")
    return True, ""


def _extract_email_id(data: dict[str, Any]) -> str:
    body = data.get("data") if isinstance(data.get("data"), dict) else {}
    eid = body.get("email_id")
    if isinstance(eid, str) and eid:
        return eid
    emails = body.get("emails") or body.get("email_ids") or []
    if isinstance(emails, list) and emails:
        first = emails[0]
        if isinstance(first, dict):
            return str(first.get("email_id") or "")
        return str(first)
    return ""


def send_test(
    config: NewsletterConfig,
    rendered: RenderedNewsletter,
    to_email: str,
) -> SendResult:
    payload = _base_payload(config, rendered)
    payload["to"] = [to_email]

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(f"{SMTP2GO_API}/email/send", headers=_headers(config), json=payload)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 400:
                return SendResult(
                    ok=False,
                    method="smtp2go-single",
                    recipient_count=1,
                    tag=rendered.tag,
                    error=_parse_error(data, resp.text),
                    details=data,
                )
            ok, err = _response_ok(data)
            if not ok:
                return SendResult(
                    ok=False,
                    method="smtp2go-single",
                    recipient_count=1,
                    tag=rendered.tag,
                    error=err,
                    details=data,
                )
            email_id = _extract_email_id(data)
            return SendResult(
                ok=True,
                method="smtp2go-single",
                recipient_count=1,
                tag=rendered.tag,
                message_ids=[email_id] if email_id else None,
                details=data,
            )
    except Exception as exc:
        return SendResult(
            ok=False,
            method="smtp2go-single",
            recipient_count=1,
            tag=rendered.tag,
            error=str(exc),
        )


def send_campaign(
    config: NewsletterConfig,
    rendered: RenderedNewsletter,
    subscribers: list[Subscriber],
    *,
    prefer_bulk: bool = True,
) -> SendResult:
    del prefer_bulk  # SMTP2GO: individual sends (tracking/unsubscribe per recipient)
    if not subscribers:
        return SendResult(
            ok=False,
            method="none",
            recipient_count=0,
            tag=rendered.tag,
            error="El segmento no tiene destinatarios.",
        )

    message_ids: list[str] = []
    try:
        with httpx.Client(timeout=120.0) as client:
            for sub in subscribers:
                payload = _base_payload(config, rendered)
                payload["to"] = [sub.email]
                resp = client.post(
                    f"{SMTP2GO_API}/email/send",
                    headers=_headers(config),
                    json=payload,
                )
                data = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    return SendResult(
                        ok=False,
                        method="smtp2go-campaign",
                        recipient_count=len(subscribers),
                        tag=rendered.tag,
                        error=_parse_error(data, f"Falló en {sub.email}"),
                        details={"email": sub.email, **data},
                        message_ids=message_ids or None,
                    )
                ok, err = _response_ok(data)
                if not ok:
                    return SendResult(
                        ok=False,
                        method="smtp2go-campaign",
                        recipient_count=len(subscribers),
                        tag=rendered.tag,
                        error=f"{sub.email}: {err}",
                        details={"email": sub.email, **data},
                        message_ids=message_ids or None,
                    )
                eid = _extract_email_id(data)
                if eid:
                    message_ids.append(eid)
    except Exception as exc:
        return SendResult(
            ok=False,
            method="smtp2go-campaign",
            recipient_count=len(subscribers),
            tag=rendered.tag,
            error=str(exc),
            message_ids=message_ids or None,
        )

    return SendResult(
        ok=True,
        method="smtp2go-campaign",
        recipient_count=len(subscribers),
        tag=rendered.tag,
        message_ids=message_ids or None,
    )
