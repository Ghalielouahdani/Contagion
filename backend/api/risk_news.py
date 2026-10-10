"""News boundary: plug any provider in through a normalized JSON feed.

No provider is selected yet. RISK_NEWS_URL is backend configuration, never a user URL.
An empty/unavailable feed must remain explicit; the model must not invent headlines.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from jsonschema import Draft202012Validator

from backend.api.risk_assistant import setting

NEWS_SCHEMA = {"type": "object", "required": ["articles"], "additionalProperties": False,
               "properties": {"articles": {"type": "array", "maxItems": 20, "items": {
                   "type": "object", "additionalProperties": False,
                   "required": ["id", "title", "summary", "url", "published_at", "source"],
                   "properties": {key: {"type": "string", "maxLength": 4000} for key in
                                  ("id", "title", "summary", "url", "published_at", "source")}}}}}


def normalize(payload: dict, origin: str) -> dict:
    if not Draft202012Validator(NEWS_SCHEMA).is_valid(payload):
        raise HTTPException(422, "News must follow the normalized articles schema (max 20).")
    ids = set()
    for article in payload["articles"]:
        if not article["id"] or article["id"] in ids or urlparse(article["url"]).scheme not in ("https", "http"):
            raise HTTPException(422, "News IDs must be unique and nonempty; source links must be HTTP(S).")
        ids.add(article["id"])
        try:
            published = datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))
            if published.tzinfo is None:
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(422, "News published_at must be an ISO timestamp with timezone.") from exc
    return {"status": "provided" if payload["articles"] else "empty", "origin": origin,
            "fetched_at": datetime.now(timezone.utc).isoformat(), **payload}


def fetch() -> dict:
    url = setting("RISK_NEWS_URL")
    if not url:
        return {"status": "not_configured", "origin": None, "fetched_at": None, "articles": []}
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(503, "RISK_NEWS_URL must be an HTTPS feed URL without embedded credentials.")
    headers = {}
    token = setting("RISK_NEWS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return normalize(response.json(), "configured_feed")
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "News feed unavailable or malformed. No headlines were invented.") from exc
