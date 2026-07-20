#!/usr/bin/env python3
"""
Ensun-style interactive runner: pick ONE country, scrape all catalogs.

Open multiple terminals and run this in each (one country per terminal).

  cd c:\\Singapore\\G4World-Scraper-main
  python run_interactive.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import go4world_config as config

WORKERS = (
    ("RM", "listings_rm"),
    ("FG", "listings_fg"),
    ("PK", "listings_pk"),
    ("MC", "listings_mc"),
)


def main() -> int:
    print("\n=== go4WorldBusiness Scraper ===\n")
    print("Pick one country. Open more terminals to run other countries in parallel.\n")

    # Ensun-style: country list only (all catalogs always)
    print("Select a country:")
    for idx, (name, _slug) in enumerate(config.TARGET_COUNTRIES, start=1):
        print(f"  {idx}. {name}")
    while True:
        raw = input("\nEnter number: ").strip()
        if not raw.isdigit():
            print("Please enter a number.")
            continue
        choice = int(raw)
        if 1 <= choice <= len(config.TARGET_COUNTRIES):
            country_name, country_slug = config.TARGET_COUNTRIES[choice - 1]
            break
        print("Invalid choice.")

    out_dir = config.COUNTRIES_OUTPUT_ROOT / country_slug.replace("-", "_")
    print("\n--- Summary ---")
    print(f"  Country : {country_name}")
    print(f"  Catalogs: RM → FG → PK → MC")
    print(f"  Output  : {out_dir / 'companies.csv'}")
    print("  Resume  : yes (re-run same country later)")
    confirm = input("\nStart scraping? [Y/n]: ").strip().lower()
    if confirm not in ("", "y", "yes"):
        print("Cancelled.")
        return 0

    prep = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_listings.py")],
        cwd=str(ROOT),
        check=False,
    )
    if prep.returncode != 0:
        print("prepare_listings failed", file=sys.stderr)
        return prep.returncode

    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["G4W_BROWSER_PROFILE_DIR"] = str(out_dir / "browser_profile")

    exit_code = 0
    for worker_id, listings_dir in WORKERS:
        cmd = [
            sys.executable,
            str(ROOT / "main_go4world.py"),
            "--listings-dir",
            str(ROOT / listings_dir),
            "--output-dir",
            str(out_dir),
            "--single-csv",
            "--skip-empty-tabs",
            "--fast",
            "--country",
            country_name,
        ]
        print(f"\n=== {country_name} | {worker_id} ===")
        print(" ".join(cmd))
        result = subprocess.run(cmd, cwd=str(ROOT), env=env, check=False)
        if result.returncode != 0:
            exit_code = result.returncode
            print(f"Warning: {worker_id} exited {result.returncode}", file=sys.stderr)

    print(f"\nDone. Output: {out_dir / 'companies.csv'}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
