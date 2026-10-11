"""News boundary: plug any provider in through a normalized JSON feed.

Two sources, both backend configuration (never a user URL):
- RISK_NEWS_URL: any feed already in the normalized articles schema (optional RISK_NEWS_TOKEN);
- RISK_NEWS_PROVIDER=cryptocurrency_cv: the free Crypto News API (https://cryptocurrency.cv, no key).
  Its full-text search only works with single words, so the adapter runs one query per term: terms
  from the portfolio's assets and protocols, plus a few keywords from the user's question (never the
  question itself). Price trackers and chart-idea posts are dropped, articles older than 14 days too.
  The Fear & Greed index is attached as market_context, separate from the articles.
An empty/unavailable feed must remain explicit; the model must not invent headlines.
"""
from __future__ import annotations

import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
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


def fetch(question: str | None = None, portfolio: dict | None = None) -> dict:
    url = setting("RISK_NEWS_URL")
    if not url:
        if setting("RISK_NEWS_PROVIDER") == "cryptocurrency_cv":
            return fetch_cryptocurrency_cv(question, portfolio)
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


# Free Crypto News API adapter ----------------------------------------------------------------
CRYPTO_NEWS_API = "https://cryptocurrency.cv/api"
USER_AGENT = "defi-contagion-risk/0.1 (portfolio stress testing)"
MAX_AGE = timedelta(days=14)
NOISE_SOURCES = {"Etherscan", "Alternative.me", "TradingView Crypto Ideas"}
MAX_QUERIES = 8
# Question words that name a macro or market channel -> the single search term that finds it.
KEYWORDS = {
    "taux": "Fed", "rate": "Fed", "rates": "Fed", "fed": "Fed", "fomc": "Fed", "powell": "Fed",
    "dollar": "dollar", "usd": "dollar", "euro": "euro", "eur": "euro", "inflation": "inflation", "cpi": "inflation",
    "tether": "Tether", "usdt": "Tether", "usdc": "USDC", "circle": "USDC", "sec": "SEC", "etf": "ETF",
    "hack": "exploit", "exploit": "exploit", "piratage": "exploit", "depeg": "depeg", "liquidation": "liquidation",
    "liquidations": "liquidation", "funding": "funding", "bitcoin": "Bitcoin", "btc": "Bitcoin", "ether": "Ethereum",
    "eth": "Ethereum", "ethena": "Ethena", "usde": "USDe", "aave": "Aave", "morpho": "Morpho", "pendle": "Pendle",
    "treasury": "Treasury", "treasuries": "Treasury", "tarifs": "tariffs", "tariffs": "tariffs", "recession": "recession",
}


def portfolio_terms(portfolio: dict | None) -> list[str]:
    """Single-word search terms for what the portfolio actually holds."""
    terms: list[str] = []
    for position in (portfolio or {}).get("positions", []):
        symbols = [position.get(k) for k in ("asset_symbol", "collateral_asset", "debt_asset") if position.get(k)]
        for symbol in symbols:
            if "USDe" in symbol:
                terms += ["Ethena", "USDe"]
            elif symbol.startswith("PT-"):
                terms.append("Pendle")
            elif symbol in ("USDC", "USDT", "PYUSD", "RLUSD", "DAI", "USDS"):
                terms.append("stablecoin")
        protocol = position.get("protocol")
        if protocol and protocol != "ethena":
            terms.append(protocol.capitalize())
    return list(dict.fromkeys(terms))


def question_terms(question: str | None) -> list[str]:
    """Up to three channel keywords from the question; the question text itself is never sent."""
    words = re.findall(r"[A-Za-zÀ-ÿ]+", question or "")
    return list(dict.fromkeys(KEYWORDS[w.lower()] for w in words if w.lower() in KEYWORDS))[:3]


def _get(path: str, params: dict) -> dict | None:
    try:
        response = httpx.get(f"{CRYPTO_NEWS_API}/{path}", params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return None


def _article(raw: dict, now: datetime) -> dict | None:
    title, link, published = raw.get("title"), raw.get("link"), raw.get("pubDate")
    if not title or not link or not published or raw.get("source") in NOISE_SOURCES:
        return None
    if urlparse(link).scheme not in ("http", "https"):
        return None
    try:
        when = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None or now - when > MAX_AGE:
        return None
    return {"id": hashlib.sha1(link.encode()).hexdigest()[:16], "title": title[:500],
            "summary": (raw.get("description") or "")[:1200], "url": link,
            "published_at": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": (raw.get("source") or "unknown")[:200]}


def fetch_cryptocurrency_cv(question: str | None, portfolio: dict | None) -> dict:
    terms = (question_terms(question) + portfolio_terms(portfolio))[:MAX_QUERIES] or ["stablecoin"]
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=len(terms) + 1) as pool:
        searches = list(pool.map(lambda term: (term, _get("search", {"q": term, "limit": 8})), terms))
        greed = pool.submit(_get, "fear-greed", {}).result()
    if all(body is None for _, body in searches):
        raise HTTPException(502, "Crypto news provider unavailable. No headlines were invented.")
    # The provider's search is fuzzy ("Fed" also returns "Federal funds" fraud stories): keep an article
    # only if the term is a whole word of its title or summary, then take the newest of each term in turn
    # so the portfolio's own exposures are never crowded out by one busy topic.
    per_term: dict[str, list[dict]] = {}
    for term, body in searches:
        word = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE if len(term) > 4 else 0)
        rows = [a for a in (_article(raw, now) for raw in (body or {}).get("articles", []))
                if a and word.search(f"{a['title']} {a['summary']}")]
        per_term[term] = sorted(rows, key=lambda a: a["published_at"], reverse=True)
    kept, found_by = [], {}
    while len(kept) < 20 and any(per_term.values()):
        for term in terms:
            if per_term.get(term) and len(kept) < 20:
                article = per_term[term].pop(0)
                if article["id"] not in found_by:
                    found_by[article["id"]] = term
                    kept.append(article)
    kept.sort(key=lambda a: a["published_at"], reverse=True)
    result = normalize({"articles": kept}, "cryptocurrency_cv")
    current = (greed or {}).get("current") or {}
    result["market_context"] = {
        "provider": "cryptocurrency.cv",
        "search_terms": terms,
        "found_by": found_by,
        "fear_greed": {"value": current.get("value"), "classification": current.get("valueClassification")} if current else None,
    }
    return result
