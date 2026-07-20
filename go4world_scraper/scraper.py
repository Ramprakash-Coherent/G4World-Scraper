"""Main orchestrator for go4worldbusiness.com listing search scraping."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

import go4world_config as config
from go4world_scraper.fetch import G4WFetchError, G4WHTTPClient
from go4world_scraper.linkedin_lookup import enrich_linkedin
from go4world_scraper.parser import (
    about_url_from_profile,
    build_search_url,
    has_next_page,
    is_empty_search_page,
    is_valid_member_profile_url,
    parse_about_minisite,
    parse_buylead_page,
    parse_products_page,
    parse_profile_page,
    parse_search_page,
    products_url_from_profile,
)
from go4world_scraper.translator import Go4WorldTranslator
from go4world_scraper.url_lookup import enrich_websites
from indiamart_scraper.storage import ensure_directories, load_progress, save_progress, slugify
from spain_scraper.listings import ListingTask, load_listings

logger = logging.getLogger(__name__)

_MERGE_TEXT_FIELDS = ("search_terms", "category_types")


@dataclass
class ScraperStats:
    listings_completed: int = 0
    searches_fetched: int = 0
    profiles_fetched: int = 0
    records_found: int = 0
    errors: int = 0
    completed_keys: list[str] = field(default_factory=list)


class Go4WorldScraper:
    def __init__(
        self,
        *,
        listings_dir: Path,
        output_dir: Path,
        cache_dir: Path,
        raw_html_dir: Path,
        progress_file: Path,
        translation_cache_file: Path,
        csv_columns: list[str],
        search_tabs: tuple[tuple[str, dict[str, str]], ...] = config.SEARCH_TABS,
        target_countries: list[tuple[str, str]] | None = None,
        base_url: str = config.BASE_URL,
        proxy_url: str | None = None,
        request_timeout: float = config.REQUEST_TIMEOUT,
        min_delay: float = config.MIN_DELAY_SECONDS,
        max_delay: float = config.MAX_DELAY_SECONDS,
        use_playwright: bool = config.USE_PLAYWRIGHT,
        headless: bool = config.HEADLESS,
        max_pages_per_search: int | None = config.MAX_PAGES_PER_SEARCH,
        max_profiles_per_listing: int | None = config.MAX_PROFILES_PER_LISTING,
        max_buyleads_per_page: int | None = config.MAX_BUYLEADS_PER_PAGE,
        enable_translation: bool = config.ENABLE_TRANSLATION,
        enable_url_lookup: bool = config.ENABLE_URL_LOOKUP,
        enable_linkedin_lookup: bool = config.ENABLE_LINKEDIN_LOOKUP,
        fetch_about_minisite: bool = config.FETCH_ABOUT_MINISITE,
        fetch_products_page: bool = config.FETCH_PRODUCTS_PAGE,
        cdp_url: str | None = None,
        single_csv_path: Path | None = None,
        skip_redundant_tabs: bool = False,
        use_cache: bool = True,
    ) -> None:
        self.listings_dir = listings_dir
        self.output_dir = output_dir
        self.cache_dir = cache_dir
        self.raw_html_dir = raw_html_dir
        self.progress_file = progress_file
        self.csv_columns = csv_columns
        self.search_tabs = search_tabs
        self.target_countries = target_countries if target_countries is not None else list(config.TARGET_COUNTRIES)
        self.base_url = base_url
        self.max_pages_per_search = max_pages_per_search
        self.max_profiles_per_listing = max_profiles_per_listing
        self.max_buyleads_per_page = max_buyleads_per_page
        self.enable_url_lookup = enable_url_lookup
        self.enable_linkedin_lookup = enable_linkedin_lookup
        self.fetch_about_minisite = fetch_about_minisite
        self.fetch_products_page = fetch_products_page
        self.single_csv_path = single_csv_path
        self.skip_redundant_tabs = skip_redundant_tabs
        self.stats = ScraperStats()
        self._last_listing_confirmed_empty = False
        self.known_company_ids: set[str] = set()
        self.http = G4WHTTPClient(
            cache_dir=cache_dir,
            timeout=request_timeout,
            min_delay=min_delay,
            max_delay=max_delay,
            user_agent=config.USER_AGENT,
            use_playwright=use_playwright,
            headless=headless,
            playwright_timeout_ms=config.PLAYWRIGHT_TIMEOUT_MS,
            challenge_wait_ms=config.CHALLENGE_WAIT_MS,
            browser_profile_dir=Path(
                os.environ.get("G4W_BROWSER_PROFILE_DIR", str(output_dir / "browser_profile"))
            ),
            proxy_url=proxy_url,
            playwright_first=bool(cdp_url) or not headless or config.PLAYWRIGHT_FIRST,
            cdp_url=cdp_url,
            use_cache=use_cache,
        )
        self.translator = Go4WorldTranslator(
            cache_file=translation_cache_file,
            source=config.TRANSLATION_SOURCE,
            target=config.TRANSLATION_TARGET,
            enabled=enable_translation,
        )

    def _entity_dir(self, entity: str) -> Path:
        return self.output_dir / slugify(entity)

    def _listing_csv_path(self, task: ListingTask) -> Path:
        return self._entity_dir(task.entity) / f"{slugify(task.listing)}.csv"

    def _task_key(self, task: ListingTask, country_slug: str | None = None) -> str:
        base = f"{slugify(task.entity)}::{slugify(task.listing)}"
        if country_slug:
            return f"{base}::{slugify(country_slug)}"
        return base

    def _normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Map internal scrape fields onto the companies.csv schema."""
        company_id = record.get("company_id") or record.get("member_id")
        profile_url = record.get("company_profile_url") or record.get("g4w_profile_url")
        verified = record.get("verified") or record.get("verified_profile")
        search_terms = record.get("search_terms") or record.get("source_listing") or record.get("new_listing")
        category_types = record.get("category_types") or record.get("source_entity")
        country = config.normalize_country_name(record.get("country")) or record.get("country")
        out = {
            "company_id": company_id,
            "company_name": record.get("company_name"),
            "company_profile_url": profile_url,
            "country": country,
            "city": record.get("city"),
            "address": record.get("address"),
            "website": record.get("website") or record.get("company_url"),
            "phone": record.get("phone"),
            "contact_person": record.get("contact_person"),
            "contact_designation": record.get("contact_designation"),
            "member_status": record.get("member_status"),
            "member_since": record.get("member_since"),
            "verified": verified,
            "verification_details": record.get("verification_details"),
            "legal_entity": record.get("legal_entity"),
            "established_year": record.get("established_year"),
            "primary_business": record.get("primary_business"),
            "role": record.get("role"),
            "products_listed_count": record.get("products_listed_count"),
            "deal_focus": record.get("deal_focus"),
            "description": record.get("description") or record.get("description_en") or record.get("about_text"),
            "search_terms": search_terms,
            "category_types": category_types,
            "search_tab": record.get("search_tab"),
            "scrape_date": record.get("scrape_date"),
        }
        return {key: out.get(key) for key in self.csv_columns}

    def _load_known_company_ids(self) -> None:
        """Load existing company_id values from companies.csv (unique-company set)."""
        paths: list[Path] = []
        if self.single_csv_path:
            paths.append(self.single_csv_path)
        else:
            paths.append(self.output_dir / "companies.csv")
        known: set[str] = set()
        for path in paths:
            if not path.exists() or path.stat().st_size == 0:
                continue
            try:
                frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not load known ids from %s: %s", path, exc)
                continue
            col = "company_id" if "company_id" in frame.columns else None
            if not col and "member_id" in frame.columns:
                col = "member_id"
            if not col:
                continue
            for value in frame[col].dropna():
                text = str(value).strip()
                if text and text.upper() != "NULL":
                    known.add(text)
        self.known_company_ids = known
        logger.info("Loaded %s known company_ids from existing CSV", len(known))

    def _company_id_of(self, record: dict[str, Any]) -> str | None:
        value = record.get("company_id") or record.get("member_id")
        if value is None:
            return None
        text = str(value).strip()
        return text if text and text.upper() != "NULL" else None

    def _apply_country_policy(
        self,
        record: dict[str, Any],
        *,
        filter_country: str | None,
    ) -> bool:
        """Normalize HQ country; drop if known HQ conflicts with filter. Return keep?"""
        raw_country = record.get("country")
        hq = config.normalize_country_name(raw_country)
        filter_canon = config.normalize_country_name(filter_country) if filter_country else None

        # City wrongly stored as country → move to city
        if raw_country and not hq:
            if not record.get("city"):
                record["city"] = raw_country
            record["country"] = None

        if hq and filter_canon and hq != filter_canon:
            logger.info(
                "Drop off-target %s (HQ=%s, filter=%s)",
                record.get("company_name") or self._company_id_of(record),
                hq,
                filter_canon,
            )
            return False

        if hq:
            record["country"] = hq
        elif filter_canon:
            record["country"] = filter_canon
        return True

    def _merge_profile(self, record: dict[str, Any], profile: dict[str, Any]) -> None:
        for key, value in profile.items():
            if not value:
                continue
            # Never let a bad profile country overwrite a good filter/search country
            # until final policy pass — still allow fill when empty or city-like.
            if key == "country":
                existing = record.get("country")
                existing_canon = config.normalize_country_name(existing)
                new_canon = config.normalize_country_name(value)
                if new_canon and (not existing_canon):
                    record["country"] = new_canon
                elif new_canon and existing_canon == new_canon:
                    record["country"] = new_canon
                continue
            existing = record.get(key)
            if not existing or str(existing).upper() == "NULL":
                record[key] = value
            elif key in {"products_capabilities", "product_details", "relationship_mapping"} and value != existing:
                record[key] = f"{existing}; {value}"

    def _write_csv(self, path: Path, records: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = [self._normalize_record(r) for r in records]
        frame = pd.DataFrame(normalized, columns=self.csv_columns)
        frame.to_csv(path, index=False, na_rep="NULL", encoding="utf-8-sig")

    @staticmethod
    def _merge_semicolon(existing: Any, new: Any) -> str | None:
        parts: list[str] = []
        seen: set[str] = set()
        for blob in (existing, new):
            if blob is None or (isinstance(blob, float) and pd.isna(blob)):
                continue
            text = str(blob).strip()
            if not text or text.upper() == "NULL":
                continue
            for piece in text.split(";"):
                cleaned = piece.strip()
                if not cleaned:
                    continue
                key = cleaned.lower()
                if key in seen:
                    continue
                seen.add(key)
                parts.append(cleaned)
        return "; ".join(parts) if parts else None

    def _record_key(self, record: dict[str, Any]) -> str:
        for field_name in ("company_id", "member_id", "company_profile_url", "g4w_profile_url", "company_name"):
            value = record.get(field_name)
            if value and str(value).strip() and str(value).upper() != "NULL":
                return str(value).strip().lower()
        return ""

    def _append_single_csv(self, records: list[dict[str, Any]]) -> int:
        if not self.single_csv_path or not records:
            return 0
        path = self.single_csv_path
        path.parent.mkdir(parents=True, exist_ok=True)
        normalized = [self._normalize_record(r) for r in records]
        new_frame = pd.DataFrame(normalized, columns=self.csv_columns)
        if path.exists() and path.stat().st_size > 0:
            existing = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
            for column in self.csv_columns:
                if column not in existing.columns:
                    existing[column] = "NULL"
            existing = existing[self.csv_columns]
            combined = pd.concat([existing, new_frame], ignore_index=True)
        else:
            combined = new_frame

        # Merge duplicates: keep first filled values; union search_terms / category_types.
        combined["_dedupe_key"] = [
            self._record_key(record) for record in combined.to_dict(orient="records")
        ]
        combined = combined[combined["_dedupe_key"] != ""]
        merged_rows: list[dict[str, Any]] = []
        seen_order: list[str] = []
        by_key: dict[str, dict[str, Any]] = {}
        for row in combined.to_dict(orient="records"):
            key = row.pop("_dedupe_key", "") or self._record_key(row)
            if not key:
                continue
            if key not in by_key:
                by_key[key] = row
                seen_order.append(key)
                continue
            current = by_key[key]
            for col in self.csv_columns:
                new_val = row.get(col)
                old_val = current.get(col)
                if col in _MERGE_TEXT_FIELDS:
                    current[col] = self._merge_semicolon(old_val, new_val)
                    continue
                empty = old_val is None or str(old_val).strip() == "" or str(old_val).upper() == "NULL"
                if empty and new_val is not None and str(new_val).upper() != "NULL":
                    current[col] = new_val
        for key in seen_order:
            merged_rows.append(by_key[key])

        out = pd.DataFrame(merged_rows, columns=self.csv_columns)
        out.to_csv(path, index=False, na_rep="NULL", encoding="utf-8-sig")
        return len(out)

    def _should_skip_listing(self, key: str, completed: set[str], no_result: set[str]) -> bool:
        return key in completed or key in no_result

    def _dedupe_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for record in records:
            if record.get("_needs_buylead_resolve"):
                continue
            key = (
                record.get("company_id")
                or record.get("member_id")
                or record.get("company_profile_url")
                or record.get("g4w_profile_url")
                or record.get("company_name")
                or ""
            )
            key = str(key).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(record)
        return unique

    def _resolve_buylead_stubs(self, stubs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        limit = self.max_buyleads_per_page or len(stubs)
        for stub in stubs[:limit]:
            buylead_url = stub.get("buylead_url")
            if not buylead_url:
                continue
            try:
                html = self.http.fetch(buylead_url)
                record = parse_buylead_page(html, buylead_url, base_url=self.base_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Buy-lead resolve failed %s: %s", buylead_url, exc)
                self.stats.errors += 1
                continue
            if record and (
                record.get("company_profile_url")
                or record.get("g4w_profile_url")
                or record.get("company_name")
            ):
                record["search_tab"] = stub.get("search_tab") or "buyers"
                resolved.append(record)
        return resolved

    def _scrape_search_tabs(
        self,
        task: ListingTask,
        scrape_date: str,
        *,
        country_name: str | None = None,
        country_slug: str | None = None,
        listing_progress: str | None = None,
    ) -> list[dict[str, Any]]:
        query = task.query
        all_records: list[dict[str, Any]] = []
        confirmed_empty = True
        progress_prefix = f"{listing_progress} | " if listing_progress else ""

        for tab_name, tab_params in self.search_tabs:
            page = 1
            tab_records: list[dict[str, Any]] = []
            tab_empty = True
            while True:
                url = build_search_url(
                    self.base_url,
                    query,
                    tab_params=tab_params,
                    page=page,
                    country_slug=country_slug,
                )
                country_part = f"_{slugify(country_slug)}" if country_slug else ""
                raw_path = (
                    self.raw_html_dir
                    / slugify(task.entity)
                    / f"{slugify(task.listing)}{country_part}_{tab_name}_p{page}.html"
                )
                try:
                    html = self.http.fetch(url, save_raw=raw_path)
                except G4WFetchError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%sSearch fetch failed %s: %s",
                        progress_prefix,
                        url,
                        exc,
                    )
                    self.stats.errors += 1
                    break

                self.stats.searches_fetched += 1
                if not is_empty_search_page(html):
                    confirmed_empty = False
                    tab_empty = False

                page_records = parse_search_page(html, url, search_tab=tab_name, base_url=self.base_url)
                stubs = [r for r in page_records if r.get("_needs_buylead_resolve")]
                members = [r for r in page_records if not r.get("_needs_buylead_resolve")]
                if stubs:
                    members.extend(self._resolve_buylead_stubs(stubs))

                for record in members:
                    record["search_country"] = country_name
                    # Do not seed country from filter yet — wait for HQ parse,
                    # then apply policy (drop off-target / fill missing).
                    record.update(
                        {
                            "source_entity": task.entity,
                            "source_listing": task.listing,
                            "new_listing": task.search_query or task.listing,
                            "search_terms": task.search_query or task.listing,
                            "category_types": task.entity,
                            "scrape_date": scrape_date,
                        }
                    )
                tab_records.extend(members)
                all_records.extend(members)
                logger.info(
                    "%sSearch | %s / %s | country=%s | tab=%s page=%s | %s companies",
                    progress_prefix,
                    task.entity,
                    task.listing,
                    country_slug or "all",
                    tab_name,
                    page,
                    len(members),
                )

                if not members and not stubs:
                    break
                if not has_next_page(html, page, search_tab=tab_name):
                    break
                if self.max_pages_per_search and page >= self.max_pages_per_search:
                    break
                page += 1

            if self.skip_redundant_tabs and tab_empty and tab_name == self.search_tabs[0][0]:
                logger.info(
                    "%sNo results on %s for %s (%s) — skipping remaining tabs",
                    progress_prefix,
                    tab_name,
                    task.listing,
                    country_slug or "all",
                )
                break

        deduped = self._dedupe_records(all_records)
        self._last_listing_confirmed_empty = confirmed_empty and not deduped
        return deduped

    def _enrich_profiles(
        self,
        records: list[dict[str, Any]],
        *,
        listing_progress: str | None = None,
    ) -> None:
        limit = self.max_profiles_per_listing or len(records)
        progress_prefix = f"{listing_progress} | " if listing_progress else ""
        for index, record in enumerate(records[:limit], start=1):
            profile_url = record.get("company_profile_url") or record.get("g4w_profile_url")
            if not profile_url or not is_valid_member_profile_url(profile_url):
                logger.warning(
                    "%sSkipping invalid profile URL: %s",
                    progress_prefix,
                    profile_url,
                )
                continue
            try:
                html = self.http.fetch(profile_url)
                profile = parse_profile_page(html, profile_url)
                self._merge_profile(record, profile)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%sProfile fetch failed %s: %s",
                    progress_prefix,
                    profile_url,
                    exc,
                )
                self.stats.errors += 1
                continue

            if self.fetch_about_minisite:
                about_url = record.get("g4w_about_url") or about_url_from_profile(profile_url)
                if about_url:
                    try:
                        about_html = self.http.fetch(about_url)
                        about = parse_about_minisite(about_html, about_url)
                        self._merge_profile(record, about)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "%sAbout/minisite fetch failed %s: %s",
                            progress_prefix,
                            about_url,
                            exc,
                        )
                        self.stats.errors += 1

            if self.fetch_products_page:
                products_url = record.get("g4w_products_url") or products_url_from_profile(profile_url)
                if products_url:
                    try:
                        products_html = self.http.fetch(products_url)
                        products = parse_products_page(products_html, products_url)
                        self._merge_profile(record, products)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "%sProducts page fetch failed %s: %s",
                            progress_prefix,
                            products_url,
                            exc,
                        )
                        self.stats.errors += 1

            if record.get("website"):
                record["company_url"] = record["website"]
            elif not record.get("company_url"):
                record["company_url"] = profile_url

            self.translator.enrich_record(record)
            self.stats.profiles_fetched += 1
            if index % 3 == 0 or index == limit:
                logger.info(
                    "%sProfiles enriched %s/%s",
                    progress_prefix,
                    index,
                    limit,
                )

    async def _enrich_external(self, records: list[dict[str, Any]]) -> None:
        if self.enable_url_lookup:
            await enrich_websites(
                records,
                min_delay=self.http.min_delay,
                max_delay=self.http.max_delay,
            )
        if self.enable_linkedin_lookup:
            await enrich_linkedin(
                records,
                min_delay=self.http.min_delay,
                max_delay=self.http.max_delay,
            )

    def _run_async(self, coro: Any) -> None:
        """Run an async coroutine even if Playwright already owns an event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, coro).result()

    def _scrape_listing_country(
        self,
        task: ListingTask,
        scrape_date: str,
        *,
        country_name: str | None,
        country_slug: str | None,
        listing_progress: str | None = None,
    ) -> list[dict[str, Any]]:
        progress_prefix = f"{listing_progress} | " if listing_progress else ""
        records = self._scrape_search_tabs(
            task,
            scrape_date,
            country_name=country_name,
            country_slug=country_slug,
            listing_progress=listing_progress,
        )
        if not records:
            return []

        # Split: already-known ids → merge terms only; new ids → enrich.
        to_enrich: list[dict[str, Any]] = []
        merge_only: list[dict[str, Any]] = []
        for record in records:
            cid = self._company_id_of(record)
            if cid and cid in self.known_company_ids:
                merge_only.append(record)
            else:
                to_enrich.append(record)

        if merge_only:
            logger.info(
                "%sSkipping enrich for %s already-known company_ids",
                progress_prefix,
                len(merge_only),
            )

        if to_enrich:
            self._enrich_profiles(to_enrich, listing_progress=listing_progress)
            try:
                self._run_async(self._enrich_external(to_enrich))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%sExternal enrichment failed (saving profile data anyway): %s",
                    progress_prefix,
                    exc,
                )
                self.stats.errors += 1

        kept: list[dict[str, Any]] = []
        for record in merge_only + to_enrich:
            if not self._apply_country_policy(record, filter_country=country_name):
                continue
            cid = self._company_id_of(record)
            if cid:
                self.known_company_ids.add(cid)
            kept.append(record)
        return kept

    def run(
        self,
        *,
        entity_filter: str | None = None,
        listing_filter: str | None = None,
        max_listings: int | None = None,
    ) -> None:
        ensure_directories(self.output_dir, self.cache_dir, self.raw_html_dir)
        self.translator.load()
        self._load_known_company_ids()
        scrape_date = date.today().isoformat()

        tasks = load_listings(self.listings_dir)
        if entity_filter:
            tasks = [task for task in tasks if slugify(task.entity) == slugify(entity_filter)]
        if listing_filter:
            slug = slugify(listing_filter)
            tasks = [
                task
                for task in tasks
                if slugify(task.listing) == slug or slugify(task.query) == slug
            ]
        if max_listings:
            tasks = tasks[:max_listings]

        progress = load_progress(self.progress_file) or {}
        completed = set(progress.get("completed_keys") or [])
        no_result = set(progress.get("no_result_keys") or [])
        stats = progress.get("stats") or {}
        listing_total = len(tasks)

        countries = self.target_countries or [(None, None)]
        logger.info(
            "Loaded %s listing tasks × %s countries | known companies=%s | url_lookup=%s linkedin=%s",
            listing_total,
            len(countries),
            len(self.known_company_ids),
            self.enable_url_lookup,
            self.enable_linkedin_lookup,
        )
        try:
            for listing_index, task in enumerate(tasks, start=1):
                listing_progress = f"Listing {listing_index}/{listing_total}"
                listing_records: list[dict[str, Any]] = []
                listing_had_results = False
                listing_all_confirmed_empty = True
                blocked = False

                logger.info(
                    "%s | %s / %s",
                    listing_progress,
                    task.entity,
                    task.listing,
                )

                for country_name, country_slug in countries:
                    key = self._task_key(task, country_slug)
                    if self._should_skip_listing(key, completed, no_result):
                        logger.info("%s | Skipping completed: %s", listing_progress, key)
                        continue

                    try:
                        records = self._scrape_listing_country(
                            task,
                            scrape_date,
                            country_name=country_name,
                            country_slug=country_slug,
                            listing_progress=listing_progress,
                        )
                    except G4WFetchError as exc:
                        logger.error("%s | Blocked on %s: %s", listing_progress, key, exc)
                        self.stats.errors += 1
                        blocked = True
                        break
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("%s | Failed %s: %s", listing_progress, key, exc)
                        self.stats.errors += 1
                        continue

                    if records:
                        listing_had_results = True
                        listing_all_confirmed_empty = False
                        listing_records.extend(records)
                        if self.single_csv_path:
                            total_rows = self._append_single_csv(records)
                            logger.info(
                                "%s | Appended %s rows to companies.csv (total now %s) -> %s",
                                listing_progress,
                                len(records),
                                total_rows,
                                self.single_csv_path,
                            )
                        completed.add(key)
                        self.stats.records_found += len(records)
                    elif getattr(self, "_last_listing_confirmed_empty", False):
                        no_result.add(key)
                        logger.info(
                            "%s | No companies for %s — marked confirmed empty",
                            listing_progress,
                            key,
                        )
                    else:
                        listing_all_confirmed_empty = False
                        logger.warning(
                            "%s | No companies parsed for %s — will retry next run",
                            listing_progress,
                            key,
                        )

                    stats.update(
                        {
                            "listings_completed": self.stats.listings_completed,
                            "searches_fetched": self.stats.searches_fetched,
                            "profiles_fetched": self.stats.profiles_fetched,
                            "records_found": self.stats.records_found,
                            "errors": self.stats.errors,
                        }
                    )
                    save_progress(
                        self.progress_file,
                        {
                            "completed_keys": sorted(completed),
                            "no_result_keys": sorted(no_result),
                            "stats": stats,
                        },
                    )

                if blocked:
                    break

                if not self.single_csv_path and listing_records:
                    out_path = self._listing_csv_path(task)
                    deduped = self._dedupe_records(listing_records)
                    self._write_csv(out_path, deduped)
                    logger.info("Wrote %s rows -> %s", len(deduped), out_path)

                if listing_had_results:
                    self.stats.listings_completed += 1
                elif listing_all_confirmed_empty and countries:
                    pass

                stats.update(
                    {
                        "listings_completed": self.stats.listings_completed,
                        "searches_fetched": self.stats.searches_fetched,
                        "profiles_fetched": self.stats.profiles_fetched,
                        "records_found": self.stats.records_found,
                        "errors": self.stats.errors,
                    }
                )
                save_progress(
                    self.progress_file,
                    {
                        "completed_keys": sorted(completed),
                        "no_result_keys": sorted(no_result),
                        "stats": stats,
                    },
                )
        finally:
            self.http.close()
            self.translator.save()
