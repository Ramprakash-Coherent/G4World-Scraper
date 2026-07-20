"""Look up LinkedIn company pages and related product snippets."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


async def lookup_linkedin(
    company_name: str,
    *,
    country: str | None = None,
    min_delay: float = 3.0,
    max_delay: float = 6.0,
) -> tuple[str | None, str | None]:
    if not company_name:
        return None, None
    await asyncio.sleep(random.uniform(min_delay, max_delay))
    suffix = f" {country}" if country else ""
    query = f'site:linkedin.com/company "{company_name}"{suffix}'
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return None, None

    def _search() -> tuple[str | None, str | None]:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=5):
                url = item.get("href") or item.get("link") or ""
                if "linkedin.com/company" in url.lower():
                    snippet = item.get("body") or ""
                    return url, snippet[:500] if snippet else None
        return None, None

    try:
        return await asyncio.to_thread(_search)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LinkedIn lookup failed for %s: %s", company_name, exc)
        return None, None


async def enrich_linkedin(records: list[dict[str, Any]], *, min_delay: float, max_delay: float) -> None:
    for record in records:
        if record.get("linkedin_url"):
            continue
        name = record.get("company_name")
        if not name:
            continue
        linkedin_url, products_info = await lookup_linkedin(
            name,
            country=record.get("country"),
            min_delay=min_delay,
            max_delay=max_delay,
        )
        if linkedin_url:
            record["linkedin_url"] = linkedin_url
        if products_info:
            record["linkedin_products_info"] = products_info
