#!/usr/bin/env python3
"""CLI entry point for the go4worldbusiness.com scraper."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import go4world_config as config
from go4world_scraper.scraper import Go4WorldScraper
from indiamart_scraper.logging_config import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape companies from go4worldbusiness.com for each entity/listing search term. "
            "Searches Suppliers and Members (entityTypeFilter=M) within a country filter; "
            "writes unique companies.csv rows (products deferred)."
        ),
    )
    parser.add_argument("--listings-dir", default=str(config.LISTINGS_DIR))
    parser.add_argument("--output-dir", default=str(config.OUTPUT_DIR))
    parser.add_argument("--entity", default=None, help="Scrape only this entity")
    parser.add_argument("--listing", default=None, help="Scrape only this listing")
    parser.add_argument(
        "--country",
        default=None,
        help="Single country (ensun-style), e.g. Japan or indonesia",
    )
    parser.add_argument(
        "--countries",
        default=None,
        help="Comma-separated countries/slugs. Example: indonesia,japan",
    )
    parser.add_argument(
        "--all-countries",
        action="store_true",
        help="Run all TARGET_COUNTRIES (explicit; avoid accidental long runs)",
    )
    parser.add_argument(
        "--enrich",
        action="store_true",
        help="Enable website URL + LinkedIn lookup (off by default for speed)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Explicit fast collection mode (default behavior; documented alias)",
    )
    parser.add_argument("--proxy", default=config.PROXY_URL, help="HTTP proxy URL (or G4W_PROXY_URL)")
    parser.add_argument("--max-listings", type=int, default=None, help="Limit listings (smoke test)")
    parser.add_argument("--no-translate", action="store_true")
    parser.add_argument("--no-url-lookup", action="store_true", help="Disable URL lookup (default)")
    parser.add_argument("--no-linkedin", action="store_true", help="Disable LinkedIn lookup (default)")
    parser.add_argument("--no-about", action="store_true", help="Skip about/minisite pages")
    parser.add_argument(
        "--products",
        action="store_true",
        help="Also fetch member products pages (off by default; products.csv later)",
    )
    parser.add_argument("--no-playwright", action="store_true")
    parser.add_argument("--headed", action="store_true", help="Show browser window for challenges")
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="Attach to real Chrome via CDP (recommended if WAF blocks headless).",
    )
    parser.add_argument("--cdp-url", default=config.CDP_URL or config.CDP_DEFAULT_URL)
    parser.add_argument(
        "--single-csv",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help=(
            "Append all results to one CSV. "
            "With no PATH, uses {output-dir}/companies.csv."
        ),
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--skip-empty-tabs",
        action="store_true",
        help="If first tab is empty, skip remaining tabs for that listing.",
    )
    parser.add_argument("--reset-progress", action="store_true")
    return parser.parse_args()


def resolve_worker_paths(output_dir: Path, single_csv_arg: str | None) -> dict[str, Path | None]:
    """Derive cache/progress/log paths from --output-dir so workers stay isolated."""
    progress_file = output_dir / "progress.json"
    if single_csv_arg is None:
        single_csv_path: Path | None = None
    elif single_csv_arg == "" or single_csv_arg in {
        str(config.SINGLE_CSV_FILE),
        "go4world_companies.csv",
        "companies.csv",
    }:
        single_csv_path = output_dir / "companies.csv"
    else:
        single_csv_path = Path(single_csv_arg)
    return {
        "cache_dir": output_dir / "cache",
        "raw_html_dir": output_dir / "raw_html",
        "progress_file": progress_file,
        "translation_cache_file": output_dir / "translation_cache.json",
        "log_file": output_dir / "go4world_scraper.log",
        "single_csv_path": single_csv_path,
    }


def resolve_countries_from_args(args: argparse.Namespace) -> list[tuple[str, str]]:
    """Resolve target countries from --country / --countries / --all-countries / interactive."""
    if args.country and args.countries:
        print("Use either --country or --countries, not both.", file=sys.stderr)
        raise SystemExit(2)
    if args.country and args.all_countries:
        print("Use either --country or --all-countries, not both.", file=sys.stderr)
        raise SystemExit(2)

    if args.all_countries:
        return list(config.TARGET_COUNTRIES)

    if args.country:
        return config.resolve_target_countries(args.country)

    if args.countries:
        return config.resolve_target_countries(args.countries)

    env_spec = os.environ.get("G4W_COUNTRIES")
    if env_spec:
        return config.resolve_target_countries(env_spec)

    # Interactive picker (ensun-style) when nothing specified
    if sys.stdin.isatty():
        print("\n=== go4WorldBusiness Scraper ===\n")
        return config.pick_country_interactive()

    print(
        "Specify --country Japan, --countries japan,indonesia, or --all-countries "
        "(or set G4W_COUNTRIES).",
        file=sys.stderr,
    )
    raise SystemExit(2)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    paths = resolve_worker_paths(output_dir, args.single_csv)

    setup_logging(paths["log_file"])

    progress_file = paths["progress_file"]
    assert isinstance(progress_file, Path)
    if args.reset_progress and progress_file.exists():
        progress_file.unlink()

    cdp_url = args.cdp_url if args.cdp or config.CDP_URL else None
    if args.cdp and not cdp_url:
        cdp_url = config.CDP_DEFAULT_URL

    target_countries = resolve_countries_from_args(args)

    # Fast collection defaults: URL/LinkedIn off unless --enrich
    enable_url = bool(args.enrich or (config.ENABLE_URL_LOOKUP and not args.no_url_lookup))
    enable_linkedin = bool(args.enrich or (config.ENABLE_LINKEDIN_LOOKUP and not args.no_linkedin))
    if args.no_url_lookup:
        enable_url = False
    if args.no_linkedin:
        enable_linkedin = False
    if args.fast:
        # Documented alias of collection defaults
        if not args.enrich:
            enable_url = False
            enable_linkedin = False

    scraper = Go4WorldScraper(
        listings_dir=Path(args.listings_dir),
        output_dir=output_dir,
        cache_dir=paths["cache_dir"],
        raw_html_dir=paths["raw_html_dir"],
        progress_file=progress_file,
        translation_cache_file=paths["translation_cache_file"],
        csv_columns=config.CSV_COLUMNS,
        target_countries=target_countries,
        proxy_url=args.proxy,
        request_timeout=config.REQUEST_TIMEOUT,
        min_delay=config.MIN_DELAY_SECONDS,
        max_delay=config.MAX_DELAY_SECONDS,
        use_playwright=not args.no_playwright,
        headless=not args.headed,
        max_pages_per_search=config.MAX_PAGES_PER_SEARCH,
        max_profiles_per_listing=config.MAX_PROFILES_PER_LISTING,
        enable_translation=not args.no_translate,
        enable_url_lookup=enable_url,
        enable_linkedin_lookup=enable_linkedin,
        fetch_about_minisite=not args.no_about,
        fetch_products_page=args.products or config.FETCH_PRODUCTS_PAGE,
        cdp_url=cdp_url,
        single_csv_path=paths["single_csv_path"],
        skip_redundant_tabs=args.skip_empty_tabs,
        use_cache=not args.no_cache,
    )
    scraper.run(
        entity_filter=args.entity,
        listing_filter=args.listing,
        max_listings=args.max_listings,
    )
    return 0 if scraper.stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
