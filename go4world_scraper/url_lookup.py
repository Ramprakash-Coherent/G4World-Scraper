"""Look up missing company websites via site: search."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BLOCKED_HOSTS = {
    "go4worldbusiness.com",
    "www.go4worldbusiness.com",
    "linkedin.com",
    "www.linkedin.com",
    "facebook.com",
    "www.facebook.com",
    "twitter.com",
    "instagram.com",
}


def _domain(url: str) -> str | None:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.") if host else None


def _is_valid_website(url: str, company_name: str) -> bool:
    domain = _domain(url)
    if not domain or domain in BLOCKED_HOSTS:
        return False
    if any(blocked in domain for blocked in BLOCKED_HOSTS):
        return False
    name_tokens = [token.lower() for token in re_split_name(company_name) if len(token) > 2]
    if not name_tokens:
        return True
    joined = domain.replace("-", "").replace(".", "")
    return any(token in joined for token in name_tokens[:4])


def re_split_name(company_name: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z0-9]+", company_name)


async def lookup_website(
    company_name: str,
    *,
    country: str | None = None,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
) -> str | None:
    if not company_name:
        return None
    await asyncio.sleep(random.uniform(min_delay, max_delay))
    queries = [
        f'"{company_name}" official website',
        f'site:.com "{company_name}"',
    ]
    if country:
        queries.insert(0, f'"{company_name}" {country} website')
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        logger.warning("duckduckgo-search not installed; skipping URL lookup")
        return None

    def _search() -> str | None:
        with DDGS() as ddgs:
            for query in queries:
                for item in ddgs.text(query, max_results=6):
                    url = item.get("href") or item.get("link") or ""
                    if url and _is_valid_website(url, company_name):
                        return url
        return None

    try:
        return await asyncio.to_thread(_search)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Website lookup failed for %s: %s", company_name, exc)
        return None


async def enrich_websites(records: list[dict[str, Any]], *, min_delay: float, max_delay: float) -> None:
    for record in records:
        if record.get("website") or (
            record.get("company_url")
            and "go4worldbusiness.com" not in str(record.get("company_url")).lower()
        ):
            continue
        name = record.get("company_name")
        if not name:
            continue
        website = await lookup_website(
            name,
            country=record.get("country"),
            min_delay=min_delay,
            max_delay=max_delay,
        )
        if website:
            record["website"] = website
            record["company_url"] = website
