"""Smoke test for go4worldbusiness scraper (offline parsers + optional live fetch)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from go4world_scraper.fetch import is_g4w_page_ready, is_waf_challenge
from go4world_scraper.parser import (
    about_url_from_profile,
    build_search_url,
    parse_about_minisite,
    parse_profile_page,
    parse_search_page,
    products_url_from_profile,
)

SAMPLE_SEARCH = """
<html><body>
<div class="search-results">
<a class="entity-row-title" href="/member/view/4149638/eec-poland-ltd-.html">EEC-Poland Ltd.</a>
<span class="verify-text">VERIFIED</span>
<span>GOLD Member</span>
<div>Supplier From Warszawa, Poland Supplier Of Fertilizers</div>
<a href="/suppliers/fertilizers.html">Fertilizers</a>
<a href="/pref_product/view/1745639/fertilizer.html">Fertilizer</a>
</div>
</body></html>
"""

SAMPLE_PROFILE = """
<html><body>
<h1>EEC-Poland Ltd.</h1>
<span class="verify-text">VERIFIED</span>
<section id="business-profile">
<p class="mn-business-summary-text">EEC-Poland Ltd. is a verified gold supplier from Warszawa, Poland.
They are a dealer/reseller specializing in fertilizers. Founded in 2008.</p>
<div class="mn-fact"><small>Primary business</small><strong>Dealer / Reseller</strong></div>
<div class="mn-fact"><small>Established</small><strong>2008</strong></div>
<div class="mn-fact"><small>Role</small><strong>Supplier</strong></div>
<div class="mn-fact"><small>Deal focus</small><strong>Sells Fertilizers</strong></div>
</section>
<section id="contact">
<div class="pn-contact-member-details">
Eec-Poland Ltd. Wybrzee 31/33, 00-379 Warszawa, Poland
Contact Person: Antoni Wasil Designation: Manager Phone: +48 123 456 789
</div>
</section>
<script type="application/ld+json">
{"@type":"FAQPage","mainEntity":[{"@type":"Question","name":"Is EEC an exporter?",
"acceptedAnswer":{"@type":"Answer","text":"EEC-Poland Ltd. is listed as an exporter on go4WorldBusiness."}}]}
</script>
</body></html>
"""

SAMPLE_ABOUT = """
<html><body>
<section id="about-member">About the Supplier Established in 2008, EEC-Poland Ltd deals in fertilizers and scrap.</section>
<section id="management">Management Leadership team information. Our Management focuses on agro products.</section>
<section id="facilities">Manufacturing Facility of EEC-Poland Ltd. operates in Warszawa, Poland.</section>
<section id="newsroom">News Room Latest company news.</section>
</body></html>
"""


def test_parser_offline() -> bool:
    import go4world_config as config
    from go4world_scraper.parser import _parse_location_blob

    url = build_search_url(
        "https://www.go4worldbusiness.com",
        "fertilizer",
        tab_params={"BuyersOrSuppliers": "suppliers"},
        page=1,
    )
    assert "searchText=fertilizer" in url
    assert "BuyersOrSuppliers=suppliers" in url

    country_url = build_search_url(
        "https://www.go4worldbusiness.com",
        "aloe-vera-extract",
        tab_params={"BuyersOrSuppliers": "suppliers", "entityTypeFilter[]": "M"},
        page=1,
        country_slug="indonesia",
    )
    if "countryFilter" not in country_url or "indonesia" not in country_url:
        print("FAIL parser: countryFilter missing", country_url)
        return False

    city, country = _parse_location_blob("Tokyo, Japan")
    if city != "Tokyo" or country != "Japan":
        print("FAIL parser: Tokyo, Japan ->", city, country)
        return False
    city, country = _parse_location_blob("Yogyakarta, DI Yogyakarta, Indonesia")
    if country != "Indonesia":
        print("FAIL parser: Indonesia location ->", city, country)
        return False
    city, country = _parse_location_blob("Tokyo")
    if country is not None:
        print("FAIL parser: bare city must not be country ->", city, country)
        return False
    if config.normalize_country_name("South Korea (Republic Of Korea)") != "South Korea":
        print("FAIL parser: korea alias")
        return False

    records = parse_search_page(
        SAMPLE_SEARCH,
        url,
        search_tab="suppliers",
    )
    if not records:
        print("FAIL parser: no search records")
        return False
    profile_url = records[0].get("g4w_profile_url") or ""
    if "4149638" not in profile_url:
        print("FAIL parser: profile URL", records[0])
        return False
    if records[0].get("company_name") != "EEC-Poland Ltd.":
        print("FAIL parser: company name", records[0])
        return False
    if records[0].get("country") != "Poland":
        print("FAIL parser: country from card", records[0])
        return False
    if records[0].get("company_id") != "4149638":
        print("FAIL parser: company_id", records[0])
        return False

    profile = parse_profile_page(
        SAMPLE_PROFILE,
        "https://www.go4worldbusiness.com/member/view/4149638/eec-poland-ltd-.html",
    )
    if profile.get("established_year") != "2008":
        print("FAIL parser: established", profile)
        return False
    if profile.get("contact_person") != "Antoni Wasil":
        print("FAIL parser: contact", profile)
        return False
    if profile.get("verified") != "yes":
        print("FAIL parser: verified", profile)
        return False
    if profile.get("country") != "Poland":
        print("FAIL parser: profile country", profile.get("country"), profile.get("city"))
        return False
    if "exporter" not in (profile.get("value_chain_classification") or "").lower():
        print("FAIL parser: value chain", profile)
        return False

    about = parse_about_minisite(
        SAMPLE_ABOUT,
        about_url_from_profile(profile_url) or "",
    )
    if not about.get("about_text") or not about.get("management_info"):
        print("FAIL parser: about/minisite", about)
        return False

    products_url = products_url_from_profile(profile_url)
    if not products_url or "/products/" not in products_url:
        print("FAIL parser: products url", products_url)
        return False

    print("PASS parser offline smoke test")
    return True


def test_live_fetch() -> bool:
    print("Live fetch test (Playwright)...")
    try:
        import go4world_config as config
        from go4world_scraper.fetch import G4WHTTPClient

        client = G4WHTTPClient(
            cache_dir=config.CACHE_DIR,
            timeout=45,
            min_delay=2.0,
            max_delay=4.0,
            user_agent=config.USER_AGENT,
            use_playwright=True,
            headless=True,
            proxy_url=os.environ.get("G4W_PROXY_URL"),
            use_proxy_pool=False,
            use_cache=False,
        )
        search_url = build_search_url(
            config.BASE_URL,
            "fertilizer",
            tab_params={"BuyersOrSuppliers": "suppliers"},
            page=1,
        )
        html = client.fetch(search_url, use_cache=False, force=True)
        if is_waf_challenge(html) or not is_g4w_page_ready(html, url=search_url):
            print("BLOCKED: WAF/challenge — use --cdp or residential proxy for full runs")
            client.close()
            return False
        records = parse_search_page(html, search_url, search_tab="suppliers")
        print(f"PASS live search: {len(records)} companies parsed")

        # Enrich one profile if available
        if records and records[0].get("g4w_profile_url"):
            profile_url = records[0]["g4w_profile_url"]
            profile_html = client.fetch(profile_url, use_cache=False, force=True)
            profile = parse_profile_page(profile_html, profile_url)
            print(
                "PASS live profile:",
                profile.get("company_name"),
                "| verified=",
                profile.get("verified_profile"),
                "| role=",
                profile.get("role"),
            )
            about_url = about_url_from_profile(profile_url)
            if about_url:
                about_html = client.fetch(about_url, use_cache=False, force=True)
                about = parse_about_minisite(about_html, about_url)
                print("PASS live about/minisite sections:", bool(about.get("about_text")))
        client.close()
        return len(records) > 0
    except Exception as exc:  # noqa: BLE001
        print(f"BLOCKED live fetch: {exc}")
        return False


def test_saved_html() -> bool:
    """Use previously probed HTML if present."""
    suppliers = ROOT / "Go4World" / "_probe" / "searchText-fertilizer_BuyersOrSuppliers-suppliers.html"
    member = ROOT / "Go4World" / "_probe" / "member_eec.html"
    about = ROOT / "Go4World" / "_probe" / "pw_member_view_about_4149638_eec_poland_ltd_html.html"
    ok = True
    if suppliers.exists():
        records = parse_search_page(
            suppliers.read_text(encoding="utf-8", errors="replace"),
            "https://www.go4worldbusiness.com/find?searchText=fertilizer&BuyersOrSuppliers=suppliers",
            search_tab="suppliers",
        )
        print(f"PASS saved search HTML: {len(records)} companies")
        ok = ok and len(records) > 0
    if member.exists():
        profile = parse_profile_page(
            member.read_text(encoding="utf-8", errors="replace"),
            "https://www.go4worldbusiness.com/member/view/4149638/eec-poland-ltd-.html",
        )
        print(
            "PASS saved profile HTML:",
            profile.get("company_name"),
            profile.get("primary_business"),
            profile.get("contact_person"),
        )
        ok = ok and bool(profile.get("company_name"))
    if about.exists():
        parsed = parse_about_minisite(
            about.read_text(encoding="utf-8", errors="replace"),
            "https://www.go4worldbusiness.com/member/view/about/4149638/eec-poland-ltd-.html",
        )
        print("PASS saved about HTML:", bool(parsed.get("about_text")), bool(parsed.get("facilities_info")))
        ok = ok and bool(parsed.get("about_text"))
    return ok


def main() -> int:
    ok = test_parser_offline()
    saved_ok = test_saved_html()
    live_ok = test_live_fetch()
    if ok and saved_ok and live_ok:
        print("SMOKE TEST: FULL PASS — scraper is ready")
        return 0
    if ok and (saved_ok or live_ok):
        print("SMOKE TEST: PARTIAL PASS — parsers work; live may need CDP/proxy under rate limits")
        return 2
    if ok:
        print("SMOKE TEST: PARSER PASS ONLY — live fetch blocked")
        return 2
    print("SMOKE TEST: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
