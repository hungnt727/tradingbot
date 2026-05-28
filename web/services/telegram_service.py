"""Telegram Bot API wrapper (Phase 6 slice 0004).

A deep module with a narrow interface: ``send_message`` returns
``(ok, error)`` and classifies failures as permanent (caller keeps the signal,
shows a warning) or transient (caller retries naturally next cycle). Used by
both the FastAPI "Test Telegram" button and the worker alert path (slice 0006).

Synchronous (httpx.Client) on purpose: the worker is a single-threaded loop, so
a sync primitive avoids dragging an event loop into it.
"""
import os

import httpx
from loguru import logger

TELEGRAM_API = "https://api.telegram.org"
DEFAULT_TIMEOUT = 5.0


def send_message(
    chat_id: str | None,
    text: str,
    *,
    token: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bool, str | None]:
    """Send ``text`` to ``chat_id``.

    Returns ``(True, None)`` on success, ``(False, reason)`` on failure. A reason
    prefixed ``transient:`` means the caller should expect a natural retry; any
    other reason is permanent (bad chat_id, bot blocked, missing token).
    """
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False, "TELEGRAM_BOT_TOKEN not configured"
    if not chat_id:
        return False, "No Telegram chat ID set"

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=timeout)
    except httpx.TimeoutException as exc:
        logger.warning(f"[telegram] timeout sending to {chat_id}: {exc}")
        return False, f"transient: timeout ({exc})"
    except httpx.HTTPError as exc:
        logger.warning(f"[telegram] network error sending to {chat_id}: {exc}")
        return False, f"transient: {exc}"

    if resp.status_code == 200:
        return True, None

    description = _describe(resp)
    if resp.status_code in (400, 403):
        # Permanent: invalid chat_id (400 "chat not found") or bot blocked (403).
        logger.warning(f"[telegram] permanent failure {resp.status_code} to {chat_id}: {description}")
        return False, description
    # 429 / 5xx and anything else: treat as transient so the worker retries.
    logger.warning(f"[telegram] transient failure {resp.status_code} to {chat_id}: {description}")
    return False, f"transient: {resp.status_code} {description}"


def _describe(resp: httpx.Response) -> str:
    try:
        return resp.json().get("description", resp.text)
    except Exception:
        return resp.text
