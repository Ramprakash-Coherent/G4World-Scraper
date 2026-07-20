# G4World-Scraper

Scraper for [go4WorldBusiness.com](https://www.go4worldbusiness.com/) company profiles from entity/listing search terms.

**This phase:** country-filtered **unique companies** → `{output-dir}/companies.csv`  
**Search tabs:** Suppliers + Members (`entityTypeFilter[]=M`) only  
**Later:** products tab / `products.csv`

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Target countries

Japan, South Korea, Singapore, Australia, Malaysia, Thailand, Vietnam, Indonesia, Philippines, Taiwan, Hong Kong, New Zealand

## companies.csv columns

```
company_id, company_name, company_profile_url, country, city, address, website, phone,
contact_person, contact_designation, member_status, member_since, verified,
verification_details, legal_entity, established_year, primary_business, role,
products_listed_count, deal_focus, description, search_terms, category_types,
search_tab, scrape_date
```

One row per `company_id`. Repeat hits merge `search_terms` / `category_types` and skip re-enrichment.

## Catalogs (4 workers)

| Worker | Source CSV | Listings dir | Output dir |
|--------|------------|--------------|------------|
| RM | `subgroups_absolute_final.csv` | `listings_rm/` | `Go4World_RM/` |
| FG | `nutraceutical_finished_goods_deduped_v1.csv` | `listings_fg/` | `Go4World_FG/` |
| PK | `packaging_deduped_v1.csv` | `listings_pk/` | `Go4World_PK/` |
| MC | `machinery_deduped_v1.csv` | `listings_mc/` | `Go4World_MC/` |

```bash
python scripts/prepare_listings.py
```

## Run (ensun-style menus)

**Easiest — interactive numbered options (like ensun):**

```powershell
cd c:\Singapore\G4World-Scraper-main
python run_interactive.py

# or just:
.\scripts\run_workers.ps1
```

You will see menus like:

```text
=== go4WorldBusiness Scraper ===

Select a worker catalog:
  1. RM — Raw Materials
  2. FG — Finished Goods
  3. PK — Packaging
  4. MC — Machinery
  5. All workers (RM → FG → PK → MC)

Enter number: 1

Select a country:
  1. Japan
  2. South Korea
  3. Singapore
  4. Australia
  5. Malaysia
  6. Thailand
  7. Vietnam
  8. Indonesia
  9. Philippines
  10. Taiwan
  11. Hong Kong
  12. New Zealand
  13. All countries (12)

Enter number: 8

Start scraping? [Y/n]: Y
```

**Non-interactive (scripted):**

```powershell
.\scripts\run_workers.ps1 -Worker RM -Country Japan
python main_go4world.py --listings-dir listings_rm --output-dir Go4World_RM --single-csv --country Japan

# Multiple countries
python main_go4world.py --listings-dir listings_pk --output-dir Go4World_PK --single-csv --countries japan,indonesia,singapore

# All 12 countries (explicit, slow)
python main_go4world.py --listings-dir listings_rm --output-dir Go4World_RM --single-csv --all-countries
.\scripts\run_workers.ps1 -Worker RM -AllCountries
```

## Parallel per country (all catalogs + resume)

Runs **countries in parallel**. For each country: **RM → FG → PK → MC** into an isolated folder (safe resume, no CSV clashes).

```powershell
cd c:\Singapore\G4World-Scraper-main

# Interactive country pick, 2 countries at a time
python run_parallel_countries.py --max-parallel 2

# Or PowerShell
.\scripts\run_parallel_countries.ps1 -MaxParallel 2

# Specific countries
python run_parallel_countries.py --countries Japan,Indonesia,Singapore --max-parallel 3

# All 12 countries, 2 at a time
python run_parallel_countries.py --all-countries --max-parallel 2
```

**Output layout:**

```text
Go4World_countries/
  japan/
    companies.csv      ← all catalogs merged, unique company_id
    progress.json      ← resume keys entity::listing::country
    parallel_runner.log
    cache/  raw_html/  browser_profile/
  indonesia/
    ...
```

**Resume:** re-run the same command; finished listing×country keys are skipped; known `company_id`s are not re-enriched.

**Recommended `--max-parallel`:** `2` (safe). `3` is usually OK. Avoid 4+ on one IP (WAF risk).

### Collection defaults (fast)

- Website URL + LinkedIn lookup **off** (enable with `--enrich`)
- Max **3** search pages / listing×country (`G4W_MAX_PAGES_PER_SEARCH`)
- Max **25** new profiles enriched per listing×country (`G4W_MAX_PROFILES_PER_LISTING`)
- Skip profile enrich when `company_id` already in `companies.csv`
- Drop companies whose HQ country conflicts with the filter (site filter is soft)
- Set `country` from parsed HQ, or fall back to the filter country when HQ is missing

```powershell
# Optional slow enrichment pass
python main_go4world.py ... --country Japan --enrich
```

## Smoke tests

```bash
python scripts/g4w_smoke_test.py
python scripts/smoke_workers.py
.\scripts\run_workers.ps1 -Smoke
```

## Resume

Re-run the same command; completed `entity::listing::country` keys in `progress.json` are skipped. Known `company_id`s are not re-enriched.

If headless is blocked: `--cdp` or `G4W_PROXY_URL`.
