"""Parse go4worldbusiness search, member profile, about/minisite, and buy-lead pages."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
MEMBER_VIEW_RE = re.compile(
    r"/member/view/(?:about/|products/)?(\d+)/([^/?#]+?)(?:\.html)?(?:$|[?#])",
    re.I,
)
BUYLEAD_RE = re.compile(r"/buylead/view/(\d+)/([^/?#]+)", re.I)
PRODUCT_RE = re.compile(r"/(?:pref_)?product/view/(\d+)/([^/?#]+)", re.I)

BLOCKED_HOST_FRAGMENTS = (
    "go4worldbusiness.com",
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    "youtube.com",
    "google",
    "cloudfront.net",
    "clarity.ms",
    "bing.com",
    "schema.org",
    "apple.com",
    "play.google",
)


def _text(element: Tag | None) -> str | None:
    if element is None:
        return None
    text = element.get_text(" ", strip=True)
    return text or None


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


MEMBER_STATUS_TOKENS = (
    "Gold Preferred",
    "GOLD Member",
    "GOLD",
    "Silver Member",
    "Silver",
    "SILVER",
    "Premium Member",
)

# Site chrome / shared support numbers — never treat as company phone.
_SITE_PHONE_BLOCKLIST = {
    "1800114649",
    "1800-114-649",
    "1-800-114-649",
    "800114649",
}

_CONTACT_SELECTORS = (
    ".pn-contact-member-details",
    ".pn-contact-copy-body",
    ".pn-contact-details",
    "[class*='pn-contact-member']",
    "[class*='contact-member']",
)

_VERIFIED_SELECTORS = (
    ".pn-verified",
    ".item-verified-div",
    ".verify-text",
    "[class*='verified']",
    "[class*='pn-verify']",
    "img[alt*='verified' i]",
    "img[title*='verified' i]",
    "[aria-label*='verified' i]",
)

_ADDRESS_CUT_MARKERS = (
    "Website:",
    "Web site:",
    "Contact Person:",
    "Designation:",
    "Phone:",
    "Tips for",
    "Send Inquiry",
    "Email:",
)


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _normalize_phone(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    lower = cleaned.lower()
    if any(
        token in lower
        for token in (
            "not displayed",
            "login",
            "inquire",
            "enquiry",
            "tips for",
            "contact person",
            "designation",
        )
    ):
        return None
    digits = _digits_only(cleaned)
    if len(digits) < 7 or len(digits) > 15:
        return None
    # Reject site-wide / toll-free support numbers and bare short hotlines.
    if digits in {_digits_only(x) for x in _SITE_PHONE_BLOCKLIST}:
        return None
    if digits.startswith("1800") or digits.startswith("800"):
        return None
    return cleaned


def _clean_address(value: str | None, *, company_name: str | None = None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    for marker in _ADDRESS_CUT_MARKERS:
        idx = re.search(re.escape(marker), text, re.I)
        if idx:
            text = text[: idx.start()]
            break
    text = _clean(text)
    if not text:
        return None
    if company_name and text.lower().startswith(company_name.lower()):
        text = _clean(text[len(company_name) :]) or text
    lower = text.lower()
    if any(token in lower for token in ("send inquiry", "not displayed", "website:", "contact person:")):
        return None
    if len(text) < 8:
        return None
    # Require at least one digit (street/postcode) or comma — avoid UI crumbs.
    if not re.search(r"\d", text) and "," not in text:
        return None
    return text


def _clean_person_name(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    for marker in ("Phone:", "Designation:", "Website:", "Tips for", "Email:", "|"):
        idx = re.search(re.escape(marker), text, re.I)
        if idx:
            text = text[: idx.start()]
            break
    text = _clean(text)
    if not text:
        return None
    lower = text.lower()
    if any(
        token in lower
        for token in ("not displayed", "phone:", "designation:", "contact person", "send inquiry")
    ):
        return None
    if len(text) < 2 or len(text) > 80:
        return None
    return text


def _clean_designation(value: str | None) -> str | None:
    text = _clean_person_name(value)
    if not text:
        return None
    lower = text.lower()
    if lower.startswith("phone") or "not displayed" in lower:
        return None
    return text


def _clean_verification_details(value: str | None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    lower = text.lower()
    if lower in {"verified", "fetching..."}:
        return None
    # Keep concise certificate phrases only.
    if "company registration certificate" in lower:
        return "Company Registration Certificate Verified"
    if "fetching" in lower:
        return None
    if "verified" in lower and len(text) > 120:
        return None
    return text[:1000]


def _clean_legal_entity(value: str | None, *, company_name: str | None = None) -> str | None:
    text = _clean(value)
    if not text:
        return None
    if company_name and text.lower() == company_name.lower():
        return None
    if len(text) < 2 or len(text) > 120:
        return None
    lower = text.lower()
    if any(token in lower for token in ("contact person", "phone:", "website:", "verified")):
        return None
    return text


def _extract_tel_phones(soup: BeautifulSoup, *, contact_root: Tag | None = None) -> list[str]:
    """Collect tel: phones; prefer links inside the contact block only."""
    phones: list[str] = []
    seen: set[str] = set()
    roots: list[BeautifulSoup | Tag] = []
    if contact_root is not None:
        roots.append(contact_root)
    else:
        # Without a contact root, do not scan the whole page (picks site hotline).
        return []
    for root in roots:
        for anchor in root.select('a[href^="tel:"], a[href^="TEL:"]'):
            href = (anchor.get("href") or "").strip()
            raw = href.split(":", 1)[-1].split("?", 1)[0]
            phone = _normalize_phone(raw) or _normalize_phone(_text(anchor))
            if phone and phone not in seen:
                seen.add(phone)
                phones.append(phone)
    return phones


def _detect_verified(soup: BeautifulSoup | Tag, page_text: str = "") -> bool:
    root = soup if isinstance(soup, BeautifulSoup) else soup
    for sel in _VERIFIED_SELECTORS:
        try:
            if root.select_one(sel):
                return True
        except Exception:  # noqa: BLE001 — some soups reject case flags on attrs
            continue
    blob = page_text or _text(root) or ""
    return bool(re.search(r"\bverified\b", blob, re.I))


def _detect_member_status(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for token in MEMBER_STATUS_TOKENS:
        if token.lower() in lower:
            if token.upper() == token:
                return token
            return token.title() if token.islower() else token
    return None


def _first_contact_block(soup: BeautifulSoup) -> Tag | None:
    for sel in _CONTACT_SELECTORS:
        try:
            node = soup.select_one(sel)
        except Exception:  # noqa: BLE001
            continue
        if node and _clean(_text(node)):
            return node
    return None


def _parse_contact_fields(soup: BeautifulSoup, *, company_name: str | None = None) -> dict[str, str]:
    """Extract address / person / designation / phone from profile contact layouts."""
    out: dict[str, str] = {}
    block = _first_contact_block(soup)
    contact_text = _text(block) or ""

    # Structured labeled rows (dt/dd, small/strong, mn-fact style)
    for label_el in soup.select(
        ".pn-contact-member-details small, .pn-contact-copy-body small, "
        ".mn-fact small, .mn-label, dt"
    ):
        lab = (_clean(_text(label_el)) or "").lower().rstrip(":")
        value_el = label_el.find_next_sibling()
        val = _clean(_text(value_el)) if value_el else None
        if not lab or not val:
            continue
        if "contact person" in lab or lab == "person":
            person = _clean_person_name(val)
            if person:
                out.setdefault("contact_person", person)
        elif "designation" in lab or lab == "title":
            designation = _clean_designation(val)
            if designation:
                out.setdefault("contact_designation", designation)
        elif lab in {"phone", "tel", "telephone", "mobile"} or lab.startswith("phone"):
            phone = _normalize_phone(val)
            if phone:
                out.setdefault("phone", phone)
        elif "address" in lab:
            addr = _clean_address(val, company_name=company_name)
            if addr:
                out.setdefault("address", addr)

    itemprop_addr = soup.select_one("[itemprop='address']")
    if itemprop_addr:
        addr = _clean_address(_text(itemprop_addr), company_name=company_name)
        if addr:
            out.setdefault("address", addr)

    if contact_text:
        person = re.search(
            r"Contact Person:\s*(.+?)(?:\s*(?:\||Designation:|Phone:|Website:|Tips for)|$)",
            contact_text,
            re.I,
        )
        designation = re.search(
            r"Designation:\s*(.+?)(?:\s*(?:\||Phone:|Website:|Tips for|Contact Person:)|$)",
            contact_text,
            re.I,
        )
        phone_matches = list(
            re.finditer(
                r"Phone:\s*(.+?)(?:\s*(?:\||Tips for|Website:|Contact Person:|Designation:)|$)",
                contact_text,
                re.I,
            )
        )
        if person:
            cleaned_person = _clean_person_name(person.group(1))
            if cleaned_person:
                out.setdefault("contact_person", cleaned_person)
        if designation:
            cleaned_desig = _clean_designation(designation.group(1))
            if cleaned_desig:
                out.setdefault("contact_designation", cleaned_desig)
        for phone_match in phone_matches:
            phone_val = _normalize_phone(phone_match.group(1))
            if phone_val:
                out.setdefault("phone", phone_val)
                break

        address_part = contact_text
        for splitter in _ADDRESS_CUT_MARKERS:
            match = re.search(re.escape(splitter), address_part, re.I)
            if match:
                address_part = address_part[: match.start()]
                break
        addr = _clean_address(address_part, company_name=company_name)
        if addr:
            out.setdefault("address", addr)

    # tel: only inside contact block (never page chrome)
    if not out.get("phone") and block is not None:
        tel_phones = _extract_tel_phones(soup, contact_root=block)
        if tel_phones:
            out["phone"] = tel_phones[0]

    return {k: v for k, v in out.items() if v}


def _apply_tel_phone(record: dict[str, Any], soup: BeautifulSoup) -> None:
    if record.get("phone"):
        return
    block = _first_contact_block(soup)
    phones = _extract_tel_phones(soup, contact_root=block)
    if phones:
        record["phone"] = phones[0]


def _join_unique(items: list[str], *, limit: int = 40) -> str | None:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = _clean(item)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return "; ".join(out) if out else None


def absolute_url(base_url: str, href: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", href)


def normalize_member_profile_url(href: str, base_url: str = "https://www.go4worldbusiness.com") -> str | None:
    if not href:
        return None
    match = MEMBER_VIEW_RE.search(href)
    if not match:
        return None
    member_id, slug = match.group(1), match.group(2)
    slug = slug.removesuffix(".html")
    return absolute_url(base_url, f"/member/view/{member_id}/{slug}.html")


def member_id_from_url(url: str) -> str | None:
    match = MEMBER_VIEW_RE.search(url or "")
    return match.group(1) if match else None


def about_url_from_profile(profile_url: str, base_url: str = "https://www.go4worldbusiness.com") -> str | None:
    match = MEMBER_VIEW_RE.search(profile_url or "")
    if not match:
        return None
    member_id, slug = match.group(1), match.group(2).removesuffix(".html")
    return absolute_url(base_url, f"/member/view/about/{member_id}/{slug}.html")


def products_url_from_profile(profile_url: str, base_url: str = "https://www.go4worldbusiness.com") -> str | None:
    match = MEMBER_VIEW_RE.search(profile_url or "")
    if not match:
        return None
    member_id, slug = match.group(1), match.group(2).removesuffix(".html")
    return absolute_url(base_url, f"/member/view/products/{member_id}/{slug}.html")


def is_valid_member_profile_url(url: str) -> bool:
    return bool(normalize_member_profile_url(url))


def is_empty_search_page(html: str) -> bool:
    lower = html.lower()
    if "no results" in lower and "entity-row-title" not in lower:
        return True
    return False


def build_search_url(
    base_url: str,
    query: str,
    *,
    tab_params: dict[str, str],
    page: int = 1,
    country_slug: str | None = None,
) -> str:
    params: list[tuple[str, str]] = [("searchText", query)]
    if country_slug:
        params.append(("countryFilter[]", country_slug))
    for key, value in tab_params.items():
        params.append((key, value))
    tab = tab_params.get("BuyersOrSuppliers", "suppliers")
    if tab == "buyers":
        if page > 1:
            params.append(("pg_buyers", str(page)))
            params.append(("pg_suppliers", "1"))
    else:
        if page > 1:
            params.append(("pg_buyers", "1"))
            params.append(("pg_suppliers", str(page)))
    params.append(("_format", "html"))
    return f"{base_url.rstrip('/')}/find?{urlencode(params)}"


_LOC_STOP_RE = re.compile(
    r"\s+(?:Inquire\s+Now|Send\s+Inquiry|Supplier\s+Of|Buyer\s+Of|Member\s+Of|"
    r"GOLD\s+Member|Silver\s+Member|VERIFIED|Call\s+Us)\b",
    re.I,
)


def _normalize_country(value: str | None) -> str | None:
    try:
        import go4world_config as config

        return config.normalize_country_name(value)
    except Exception:  # noqa: BLE001
        return value


def _parse_location_blob(blob: str | None) -> tuple[str | None, str | None]:
    """Split location text into (city, country).

    Never treats a bare city as country. Uses known-country matching when possible.
    """
    text = _clean(blob)
    if not text:
        return None, None
    text = _LOC_STOP_RE.split(text, maxsplit=1)[0].strip(" ,;")
    # Also split on " - " often used before country in addresses
    text = text.replace(" - ", ", ")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return None, None

    # Walk from the end: first known country wins as country.
    country: str | None = None
    country_idx = -1
    for idx in range(len(parts) - 1, -1, -1):
        canonical = _normalize_country(parts[idx])
        if canonical:
            country = canonical
            country_idx = idx
            break

    if country is not None:
        city_parts = parts[:country_idx] if country_idx > 0 else []
        city = _clean(", ".join(city_parts)) if city_parts else None
        # If first segment alone looks like a city (not a country), use it
        if city and _normalize_country(city_parts[0] if city_parts else None):
            # Entire prefix was another country — keep city None
            if len(city_parts) == 1:
                city = None
        return city, country

    if len(parts) == 1:
        # Unknown single token: do NOT put it in country (avoid Tokyo-as-country).
        return parts[0], None

    # Unknown multi-segment: last as provisional country only if it looks country-like
    # (contains space or is long); otherwise leave country empty.
    last = parts[-1]
    if _normalize_country(last) or (" " in last and len(last) > 4):
        return parts[0], last
    return parts[0], None


def has_next_page(html: str, current_page: int, *, search_tab: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    next_page = current_page + 1
    page_key = "pg_buyers" if search_tab == "buyers" else "pg_suppliers"
    for anchor in soup.select("a[href]"):
        href = anchor.get("href") or ""
        if f"{page_key}={next_page}" in href:
            return True
        label = anchor.get_text(strip=True)
        if label in {str(next_page), "Next", "»", "›"} and page_key.split("=")[0] in href:
            return True
    return False


def _nearest_card(anchor: Tag) -> Tag:
    card = anchor
    for _ in range(8):
        parent = card.parent
        if parent is None:
            break
        classes = " ".join(parent.get("class") or []).lower()
        if any(token in classes for token in ("entity-row", "search-result", "result", "card", "row")):
            card = parent
            if "entity-row" in classes:
                break
        card = parent
    return card


def _parse_member_anchor(anchor: Tag, *, search_tab: str, base_url: str) -> dict[str, Any] | None:
    href = anchor.get("href") or ""
    profile_url = normalize_member_profile_url(href, base_url)
    if not profile_url:
        return None
    name = _clean(_text(anchor))
    if not name or name.lower() in {"verified", "inquire now", "view details", "send inquiry"}:
        # Try title on nearby heading
        card = _nearest_card(anchor)
        heading = card.select_one(".entity-row-title, h2, h3")
        if heading:
            name = _clean(_text(heading))
    if not name:
        return None

    card = _nearest_card(anchor)
    card_text = card.get_text(" ", strip=True)
    verified = _detect_verified(card, card_text)
    member_status = _detect_member_status(card_text)

    city = country = None
    loc_match = re.search(
        r"(?:Supplier|Buyer|Member)\s+From\s+(.+)",
        card_text,
        re.I,
    )
    if loc_match:
        city, country = _parse_location_blob(loc_match.group(1))
        if country:
            country = _normalize_country(country) or country
        # If "country" is actually a city, clear it
        if country and not _normalize_country(country) and city is None:
            city, country = country, None

    products: list[str] = []
    for prod in card.select('a[href*="/suppliers/"], a[href*="/buyers/"]'):
        label = _clean(_text(prod))
        if label and "supplier of" not in label.lower() and "buyer of" not in label.lower():
            products.append(label)

    member_id = member_id_from_url(profile_url)
    return {
        "company_name": name,
        "company_id": member_id,
        "company_profile_url": profile_url,
        "g4w_profile_url": profile_url,
        "member_id": member_id,
        "verified": "yes" if verified else None,
        "verified_profile": "yes" if verified else None,
        "member_status": member_status,
        "city": city,
        "country": country,
        "products_capabilities": _join_unique(products, limit=20),
        "search_tab": search_tab,
    }


def _extract_buylead_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="/buylead/view/"]'):
        href = absolute_url(base_url, anchor.get("href") or "")
        key = href.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        urls.append(key)
    return urls


def parse_search_page(
    html: str,
    page_url: str,
    *,
    search_tab: str,
    base_url: str = "https://www.go4worldbusiness.com",
) -> list[dict[str, Any]]:
    if is_empty_search_page(html):
        return []

    soup = BeautifulSoup(html, "html.parser")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for anchor in soup.select('a[href*="/member/view/"]'):
        href = anchor.get("href") or ""
        if "/member/view/about/" in href or "/member/view/products/" in href:
            continue
        record = _parse_member_anchor(anchor, search_tab=search_tab, base_url=base_url)
        if not record:
            continue
        profile_url = record["g4w_profile_url"]
        if profile_url in seen:
            continue
        seen.add(profile_url)
        records.append(record)

    # Buyers tab often has buy-leads without member links on the card.
    if search_tab == "buyers":
        for buylead_url in _extract_buylead_urls(html, base_url):
            records.append(
                {
                    "company_name": None,
                    "g4w_profile_url": None,
                    "buylead_url": buylead_url,
                    "search_tab": search_tab,
                    "_needs_buylead_resolve": True,
                }
            )

    return records


def parse_buylead_page(html: str, buylead_url: str, *, base_url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select('a[href*="/member/view/"]'):
        href = anchor.get("href") or ""
        if "/member/view/about/" in href or "/member/view/products/" in href:
            continue
        record = _parse_member_anchor(anchor, search_tab="buyers", base_url=base_url)
        if record:
            record["buylead_url"] = buylead_url
            return record

    # Fallback: title often contains "buyer from <country>"
    title = _clean(_text(soup.find("h1")) or _text(soup.find("h2")))
    if not title:
        return None
    return {
        "company_name": title,
        "g4w_profile_url": None,
        "buylead_url": buylead_url,
        "search_tab": "buyers",
        "description": _clean(_text(soup.select_one(".entity-row-description-search, .description, p"))),
    }


def _fact_map(soup: BeautifulSoup) -> dict[str, str]:
    facts: dict[str, str] = {}
    for fact in soup.select(".mn-fact"):
        label = _clean(_text(fact.find("small")))
        value = _clean(_text(fact.find("strong")))
        if label and value:
            facts[label.lower()] = value
    return facts


def _section_text(soup: BeautifulSoup, section_id: str) -> str | None:
    section = soup.select_one(f"#{section_id}")
    if not section:
        return None
    text = _clean(section.get_text(" ", strip=True))
    if not text:
        return None
    # Drop noisy inquiry widgets if they got nested somehow
    return text[:4000]


def _extract_external_website(soup: BeautifulSoup) -> str | None:
    for anchor in soup.select("a[href]"):
        href = (anchor.get("href") or "").strip()
        if not href.startswith("http"):
            continue
        host = urlparse(href).netloc.lower()
        if any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS):
            continue
        label = (_text(anchor) or "").lower()
        if "website" in label or "www." in label or "." in host:
            return href
    # Plain-text website mentions
    page_text = soup.get_text("\n", strip=True)
    match = re.search(r"(?:Website|Web\s*site)\s*[:\-]?\s*((?:https?://)?www\.[^\s<>]+)", page_text, re.I)
    if match:
        url = match.group(1)
        if not url.startswith("http"):
            url = "https://" + url
        host = urlparse(url).netloc.lower()
        if not any(fragment in host for fragment in BLOCKED_HOST_FRAGMENTS):
            return url
    return None


def _parse_faq_roles(soup: BeautifulSoup) -> list[str]:
    roles: list[str] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        entities = data if isinstance(data, list) else [data]
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            if entity.get("@type") != "FAQPage":
                continue
            for item in entity.get("mainEntity") or []:
                answer = ((item.get("acceptedAnswer") or {}).get("text") or "").lower()
                question = (item.get("name") or "").lower()
                blob = f"{question} {answer}"
                for role in (
                    "manufacturer",
                    "distributor",
                    "importer",
                    "exporter",
                    "supplier",
                    "buyer",
                    "dealer",
                    "reseller",
                    "wholesaler",
                    "service provider",
                    "partner",
                ):
                    if role in blob:
                        roles.append(role)
    return roles


def parse_profile_page(html: str, profile_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    member_id = member_id_from_url(profile_url)
    record: dict[str, Any] = {
        "company_id": member_id,
        "company_profile_url": profile_url,
        "g4w_profile_url": profile_url,
        "member_id": member_id,
        "g4w_about_url": about_url_from_profile(profile_url),
        "g4w_products_url": products_url_from_profile(profile_url),
    }

    h1 = soup.find("h1")
    if h1:
        record["company_name"] = _clean(h1.get_text(" ", strip=True))

    summary = _clean(_text(soup.select_one(".mn-business-summary-text, .mn-business-summary")))
    if summary:
        record["description"] = summary

    facts = _fact_map(soup)
    mapping = {
        "primary business": "primary_business",
        "established": "established_year",
        "annual sales": "annual_sales",
        "role": "role",
        "products listed": "products_listed_count",
        "deal focus": "deal_focus",
        "legal entity": "legal_entity",
        "business type": "primary_business",
    }
    for label, key in mapping.items():
        if label in facts and not record.get(key):
            record[key] = facts[label]

    contact_fields = _parse_contact_fields(soup, company_name=record.get("company_name"))
    for key, value in contact_fields.items():
        if value and not record.get(key):
            record[key] = value

    _apply_tel_phone(record, soup)

    page_text = soup.get_text("\n", strip=True)

    member_since = re.search(r"Member since\s+([^.\n|]+)", page_text, re.I)
    if member_since:
        record["member_since"] = _clean(member_since.group(1))

    # Prefer fact block; reject legal_entity that is just the company name.
    legal = re.search(r"Legal Entity\s*:\s*([^\n|]+)", page_text, re.I)
    if legal and not record.get("legal_entity"):
        record["legal_entity"] = legal.group(1)
    if record.get("legal_entity"):
        record["legal_entity"] = _clean_legal_entity(
            record.get("legal_entity"),
            company_name=record.get("company_name"),
        )

    # Sidebar / header location e.g. "Supplier from Indonesia" or "from Yogyakarta, Indonesia"
    loc_header = re.search(
        r"(?:Supplier|Buyer|Member)\s+from\s+([^\n.|]+)",
        page_text,
        re.I,
    )
    if loc_header:
        city, country = _parse_location_blob(loc_header.group(1))
        if city and not _normalize_country(city):
            record["city"] = city
        if country:
            record["country"] = country

    # Summary: "from Tokyo, Japan"
    if summary:
        loc = re.search(
            r"from\s+([A-Za-z0-9][^.]{0,80}?)(?:\.|\s{2}|$)",
            summary,
            re.I,
        )
        if loc:
            city, country = _parse_location_blob(loc.group(1))
            if city and not record.get("city") and not _normalize_country(city):
                record["city"] = city
            if country:
                # Prefer known country from summary over a city wrongly stored as country
                existing_country = _normalize_country(record.get("country"))
                if not existing_country or existing_country == country:
                    record["country"] = country
                elif not _normalize_country(record.get("country")):
                    record["country"] = country

    # Address tail often ends with country
    if record.get("address") and not _normalize_country(record.get("country")):
        _city, addr_country = _parse_location_blob(record["address"])
        if addr_country:
            record["country"] = addr_country
        if _city and not record.get("city") and not _normalize_country(_city):
            record["city"] = _city

    # Normalize country field; clear if it is still a city name
    canonical = _normalize_country(record.get("country"))
    if canonical:
        record["country"] = canonical
    elif record.get("country") and not _normalize_country(record.get("country")):
        # Likely a city wrongly assigned — move to city if empty
        if not record.get("city"):
            record["city"] = record.get("country")
        record["country"] = None

    emails = EMAIL_RE.findall(page_text)
    if emails:
        record["email"] = emails[0]

    website = _extract_external_website(soup)
    if website:
        record["website"] = website
        record["company_url"] = website

    if _detect_verified(soup, page_text):
        record["verified"] = "yes"
        record["verified_profile"] = "yes"
    verification = soup.select_one(
        ".showDocuments, .member_documents_hover_window, [class*='verif']"
    )
    if verification:
        details = _clean_verification_details(verification.get_text(" ", strip=True))
        if details:
            record["verification_details"] = details
    elif "Company Registration Certificate Verified" in page_text:
        record["verification_details"] = "Company Registration Certificate Verified"

    # Member badge: prefer header/card chrome, not full page (avoids UI "Premium").
    badge_text = " ".join(
        filter(
            None,
            [
                _text(soup.select_one("h1")),
                _text(soup.select_one(".pn-member-type, .member-type, [class*='member-status'], [class*='member-type']")),
                _text(soup.select_one(".mn-business-summary-text, .mn-business-summary")),
            ],
        )
    )
    status = _detect_member_status(badge_text) or _detect_member_status(
        " ".join(
            _text(node) or ""
            for node in soup.select("[class*='gold'], [class*='silver'], [class*='premium'], .verify-text")
        )
    )
    if status:
        record["member_status"] = status

    geo_parts = []
    for key in ("address", "city", "country"):
        value = record.get(key)
        if value and "send inquiry" not in value.lower() and "dealer" not in value.lower():
            geo_parts.append(value)
    if geo_parts:
        record["geographic_footprint"] = _join_unique(geo_parts)

    roles = _parse_faq_roles(soup)
    if record.get("primary_business"):
        roles.append(record["primary_business"])
    if record.get("role"):
        roles.append(record["role"])
    if roles:
        record["value_chain_classification"] = _join_unique(roles)
        record["relationship_mapping"] = _join_unique(roles)

    if record.get("deal_focus"):
        record["products_capabilities"] = record["deal_focus"]

    return record

def parse_about_minisite(html: str, about_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    record: dict[str, Any] = {"g4w_about_url": about_url}

    about = _section_text(soup, "about-member")
    if about:
        record["about_text"] = about
        if not record.get("description"):
            record["description"] = about[:1500]

    management = _section_text(soup, "management")
    if management:
        record["management_info"] = management[:2500]

    facilities = _section_text(soup, "facilities")
    if facilities:
        record["facilities_info"] = facilities[:2500]

    newsroom = _section_text(soup, "newsroom")
    if newsroom:
        record["newsroom_info"] = newsroom[:2000]

    # Facility facts
    facts: list[str] = []
    for label in soup.select(".mn-label, .mn-facility-facts-block small, dt"):
        value_el = label.find_next_sibling()
        lab = _clean(_text(label))
        val = _clean(_text(value_el)) if value_el else None
        if lab and val:
            facts.append(f"{lab}: {val}")
    if facts:
        existing = record.get("facilities_info") or ""
        record["facilities_info"] = _clean((existing + " | " + " | ".join(facts[:20])).strip(" |"))

    # Supplier / buyer product lists on about page
    deals = soup.select_one(".mn-about-deals-block, .mn-facility-facts-block")
    if deals:
        deal_text = _clean(deals.get_text(" ", strip=True))
        if deal_text:
            record["products_capabilities"] = deal_text[:2000]
            lower = deal_text.lower()
            roles = []
            for role in ("supplier", "buyer", "manufacturer", "exporter", "importer", "distributor"):
                if role in lower:
                    roles.append(role)
            if roles:
                record["relationship_mapping"] = _join_unique(roles)

    website = _extract_external_website(soup)
    if website:
        record["website"] = website
        record["company_url"] = website

    contact_fields = _parse_contact_fields(soup, company_name=record.get("company_name"))
    for key, value in contact_fields.items():
        if value and not record.get(key):
            record[key] = value
    _apply_tel_phone(record, soup)

    return record


def parse_products_page(html: str, products_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    products: list[str] = []
    for title in soup.select(".entity-row-title, h3 a, h3"):
        name = _clean(_text(title))
        if name and name.lower() not in {"products", "send inquiry"}:
            products.append(name)
    # Also product links
    for anchor in soup.select('a[href*="/pref_product/view/"], a[href*="/product/view/"]'):
        name = _clean(_text(anchor))
        if name:
            products.append(name)
    joined = _join_unique(products, limit=50)
    return {
        "g4w_products_url": products_url,
        "product_details": joined,
        "products_capabilities": joined,
        "products_listed_count": str(len(set(p.lower() for p in products))) if products else None,
    }
