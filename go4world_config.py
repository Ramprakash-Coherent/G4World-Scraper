"""Configuration for the go4worldbusiness.com scraper."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Paths ---
LISTINGS_DIR = BASE_DIR / "listings"
OUTPUT_DIR = BASE_DIR / "Go4World"
SINGLE_CSV_FILE = OUTPUT_DIR / "companies.csv"
CACHE_DIR = OUTPUT_DIR / "cache"
RAW_HTML_DIR = OUTPUT_DIR / "raw_html"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"
LOG_FILE = OUTPUT_DIR / "go4world_scraper.log"
TRANSLATION_CACHE_FILE = OUTPUT_DIR / "translation_cache.json"
PROXY_LIST_FILE = OUTPUT_DIR / "proxies.txt"
# Per-process override for parallel country runs (avoids Playwright profile lock).
BROWSER_PROFILE_DIR = Path(
    os.environ.get("G4W_BROWSER_PROFILE_DIR", str(OUTPUT_DIR / "browser_profile"))
)
# Fresh enriched runs write here. Legacy tree is never written by default.
COUNTRIES_OUTPUT_ROOT = BASE_DIR / "Go4World_countries_enriched"
COUNTRIES_OUTPUT_ROOT_LEGACY = BASE_DIR / "Go4World_countries"

# --- Site ---
BASE_URL = "https://www.go4worldbusiness.com"
SEARCH_PATH = "/find"

# Suppliers + Members only (matches site Find Suppliers + entityTypeFilter[]=M).
SEARCH_TABS = (
    ("suppliers", {"BuyersOrSuppliers": "suppliers"}),
    ("companies", {"BuyersOrSuppliers": "suppliers", "entityTypeFilter[]": "M"}),
)

# Asia-Pacific countries only (display name, countryFilter[] slug).
TARGET_COUNTRIES: tuple[tuple[str, str], ...] = (
    ("Japan", "japan"),
    ("South Korea", "south-korea"),
    ("Singapore", "singapore"),
    ("Australia", "australia"),
    ("Malaysia", "malaysia"),
    ("Thailand", "thailand"),
    ("Vietnam", "vietnam"),
    ("Indonesia", "indonesia"),
    ("Philippines", "philippines"),
    ("Taiwan", "taiwan"),
    ("Hong Kong", "hong-kong"),
    ("New Zealand", "new-zealand"),
)

# Aliases → canonical TARGET_COUNTRIES display name.
COUNTRY_ALIASES: dict[str, str] = {
    "japan": "Japan",
    "south korea": "South Korea",
    "south-korea": "South Korea",
    "korea": "South Korea",
    "republic of korea": "South Korea",
    "s.korea": "South Korea",
    "s korea": "South Korea",
    "singapore": "Singapore",
    "australia": "Australia",
    "malaysia": "Malaysia",
    "thailand": "Thailand",
    "vietnam": "Vietnam",
    "viet nam": "Vietnam",
    "indonesia": "Indonesia",
    "philippines": "Philippines",
    "the philippines": "Philippines",
    "taiwan": "Taiwan",
    "hong kong": "Hong Kong",
    "hong-kong": "Hong Kong",
    "new zealand": "New Zealand",
    "new-zealand": "New Zealand",
    # Common off-target HQs we still recognize for drop logic
    "china": "China",
    "people's republic of china": "China",
    "india": "India",
    "united states": "United States",
    "usa": "United States",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "france": "France",
    "italy": "Italy",
    "germany": "Germany",
    "canada": "Canada",
    "south africa": "South Africa",
    "pakistan": "Pakistan",
    "poland": "Poland",
    "uae": "United Arab Emirates",
    "united arab emirates": "United Arab Emirates",
}

# --- Proxy ---
PROXY_URL: str | None = os.environ.get("G4W_PROXY_URL")
NO_PROXY: bool = os.environ.get("G4W_NO_PROXY", "1").lower() in ("1", "true", "yes")

# --- HTTP / anti-block ---
REQUEST_TIMEOUT = float(os.environ.get("G4W_REQUEST_TIMEOUT", "60"))
PLAYWRIGHT_TIMEOUT_MS = int(os.environ.get("G4W_PLAYWRIGHT_TIMEOUT_MS", "120000"))
CHALLENGE_WAIT_MS = int(os.environ.get("G4W_CHALLENGE_WAIT_MS", "180000"))
PLAYWRIGHT_FIRST = os.environ.get("G4W_PLAYWRIGHT_FIRST", "1").lower() in ("1", "true", "yes")
CDP_URL: str | None = os.environ.get("G4W_CDP_URL")
CDP_DEFAULT_URL = os.environ.get("G4W_CDP_DEFAULT_URL", "http://127.0.0.1:9222")
MAX_RETRIES = max(1, int(os.environ.get("G4W_MAX_RETRIES", "5")))
USE_PLAYWRIGHT = os.environ.get("G4W_USE_PLAYWRIGHT", "1").lower() in ("1", "true", "yes")
HEADLESS = os.environ.get("G4W_HEADLESS", "1").lower() in ("1", "true", "yes")

MIN_DELAY_SECONDS = float(os.environ.get("G4W_MIN_DELAY", "5.0"))
MAX_DELAY_SECONDS = float(os.environ.get("G4W_MAX_DELAY", "10.0"))

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Collection defaults: fewer pages / capped profiles (override via env).
_max_pages = os.environ.get("G4W_MAX_PAGES_PER_SEARCH", "3").strip()
MAX_PAGES_PER_SEARCH: int | None = (
    int(_max_pages) if _max_pages.isdigit() and int(_max_pages) > 0 else None
)

# 0 / empty / non-positive = unlimited (enrich every company found on a listing).
_max_profiles = os.environ.get("G4W_MAX_PROFILES_PER_LISTING", "0").strip()
MAX_PROFILES_PER_LISTING: int | None = (
    int(_max_profiles) if _max_profiles.isdigit() and int(_max_profiles) > 0 else None
)

_max_buyleads = os.environ.get("G4W_MAX_BUYLEADS_PER_PAGE", "8").strip()
MAX_BUYLEADS_PER_PAGE: int | None = (
    int(_max_buyleads) if _max_buyleads.isdigit() and int(_max_buyleads) > 0 else None
)

# --- Translation ---
ENABLE_TRANSLATION = os.environ.get("G4W_ENABLE_TRANSLATION", "1").lower() in ("1", "true", "yes")
TRANSLATION_SOURCE = os.environ.get("G4W_TRANSLATION_SOURCE", "auto")
TRANSLATION_TARGET = "en"

# --- Enrichment (collection-fast defaults: URL/LinkedIn off; opt in with --enrich) ---
ENABLE_URL_LOOKUP = os.environ.get("G4W_ENABLE_URL_LOOKUP", "0").lower() in ("1", "true", "yes")
ENABLE_LINKEDIN_LOOKUP = os.environ.get("G4W_ENABLE_LINKEDIN_LOOKUP", "0").lower() in ("1", "true", "yes")
FETCH_ABOUT_MINISITE = os.environ.get("G4W_FETCH_ABOUT", "1").lower() in ("1", "true", "yes")
FETCH_PRODUCTS_PAGE = os.environ.get("G4W_FETCH_PRODUCTS", "0").lower() in ("1", "true", "yes")

# --- Output ---
CSV_COLUMNS = [
    "company_id",
    "company_name",
    "company_profile_url",
    "country",
    "city",
    "address",
    "website",
    "phone",
    "contact_person",
    "contact_designation",
    "member_status",
    "member_since",
    "verified",
    "verification_details",
    "legal_entity",
    "established_year",
    "primary_business",
    "role",
    "products_listed_count",
    "deal_focus",
    "description",
    "search_terms",
    "category_types",
    "search_tab",
    "scrape_date",
]

TARGET_COUNTRY_NAMES = {name for name, _ in TARGET_COUNTRIES}


def normalize_country_name(value: str | None) -> str | None:
    """Map a free-text country/city-country token to a canonical country name."""
    if not value:
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    key = text.lower().replace("_", " ").replace("-", " ")
    key = " ".join(key.split())
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    # Exact TARGET display match
    for name, _ in TARGET_COUNTRIES:
        if name.lower() == key:
            return name
    # Suffix match: "... South Korea (Republic Of Korea)"
    for alias, canonical in sorted(COUNTRY_ALIASES.items(), key=lambda x: -len(x[0])):
        if key.endswith(alias) or alias in key:
            # Prefer exact-ish containment for multi-word aliases
            if alias in key:
                return canonical
    return None


def is_target_country(name: str | None) -> bool:
    canonical = normalize_country_name(name)
    return canonical in TARGET_COUNTRY_NAMES if canonical else False


def resolve_target_countries(spec: str | None = None) -> list[tuple[str, str]]:
    """Parse a comma-separated country filter into (display_name, slug) pairs.

    Accepts display names or URL slugs (case-insensitive). Empty/None → all targets.
    """
    if not spec or not str(spec).strip():
        return list(TARGET_COUNTRIES)

    by_slug = {slug.lower(): (name, slug) for name, slug in TARGET_COUNTRIES}
    by_name = {name.lower(): (name, slug) for name, slug in TARGET_COUNTRIES}
    selected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for token in str(spec).split(","):
        raw = token.strip()
        if not raw:
            continue
        key = raw.lower().replace("_", "-").replace(" ", "-")
        match = by_slug.get(key) or by_name.get(raw.lower())
        if match is None:
            canonical = normalize_country_name(raw)
            if canonical and canonical in by_name:
                match = by_name[canonical.lower()]
        if match is None:
            display = raw.replace("-", " ").title()
            match = (display, key)
        if match[1] in seen:
            continue
        seen.add(match[1])
        selected.append(match)
    return selected or list(TARGET_COUNTRIES)


def pick_country_interactive() -> list[tuple[str, str]]:
    """Numbered country menu (ensun-style). Returns one country or all."""
    print("Select a country:")
    for idx, (name, _slug) in enumerate(TARGET_COUNTRIES, start=1):
        print(f"  {idx}. {name}")
    all_idx = len(TARGET_COUNTRIES) + 1
    print(f"  {all_idx}. All countries ({len(TARGET_COUNTRIES)})")
    while True:
        raw = input("\nEnter number: ").strip()
        if not raw.isdigit():
            print("Please enter a number.")
            continue
        choice = int(raw)
        if 1 <= choice <= len(TARGET_COUNTRIES):
            selected = TARGET_COUNTRIES[choice - 1]
            print(f"\nSelected country: {selected[0]}")
            return [selected]
        if choice == all_idx:
            print(f"\nSelected: all {len(TARGET_COUNTRIES)} target countries")
            return list(TARGET_COUNTRIES)
        print("Invalid choice.")


def pick_worker_interactive() -> str | None:
    """Numbered worker menu. Returns RM/FG/PK/MC or None for all workers."""
    workers = ("RM", "FG", "PK", "MC")
    labels = {
        "RM": "Raw Materials",
        "FG": "Finished Goods",
        "PK": "Packaging",
        "MC": "Machinery",
    }
    print("\nSelect a worker catalog:")
    for idx, wid in enumerate(workers, start=1):
        print(f"  {idx}. {wid} — {labels[wid]}")
    print(f"  {len(workers) + 1}. All workers (RM → FG → PK → MC)")
    while True:
        raw = input("\nEnter number: ").strip()
        if not raw.isdigit():
            print("Please enter a number.")
            continue
        choice = int(raw)
        if 1 <= choice <= len(workers):
            selected = workers[choice - 1]
            print(f"Selected worker: {selected}")
            return selected
        if choice == len(workers) + 1:
            print("Selected: all workers")
            return None
        print("Invalid choice.")


def confirm_start(*, worker: str, country_label: str) -> bool:
    """Ask Y/n before scraping (ensun-style)."""
    print("\n--- Summary ---")
    print(f"  Worker : {worker}")
    print(f"  Country: {country_label}")
    print(f"  Output : Go4World_{worker}/companies.csv" if worker != "ALL" else "  Output : Go4World_RM|FG|PK|MC/companies.csv")
    raw = input("\nStart scraping? [Y/n]: ").strip().lower()
    return raw in ("", "y", "yes")
