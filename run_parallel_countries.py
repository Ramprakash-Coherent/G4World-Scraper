#!/usr/bin/env python3
"""
Run go4WorldBusiness scrape in parallel — one process per country.

Each country:
  - runs all catalogs (RM → FG → PK → MC)
  - writes to Go4World_countries/{slug}/companies.csv
  - has its own progress.json (resume-safe)
  - has its own browser_profile / cache (no Playwright lock fights)

Examples:
  python run_parallel_countries.py --max-parallel 2
  python run_parallel_countries.py --countries Japan,Indonesia,Singapore --max-parallel 3
  python run_parallel_countries.py --all-countries --max-parallel 2
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _country_out_dir(slug: str) -> Path:
    return config.COUNTRIES_OUTPUT_ROOT / slug.replace("-", "_")


def run_one_country(country_name: str, country_slug: str, *, reset_progress: bool = False) -> int:
    """Run all catalogs for one country into an isolated output folder."""
    out_dir = _country_out_dir(country_slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "parallel_runner.log"
    profile_dir = out_dir / "browser_profile"

    env = os.environ.copy()
    env["G4W_BROWSER_PROFILE_DIR"] = str(profile_dir)

    print(f"[START] {country_name} -> {out_dir}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n===== START {country_name} {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")

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
            if reset_progress and worker_id == "RM":
                # Only reset once at the start of the country pipeline
                cmd.append("--reset-progress")

            header = f"\n--- {country_name} / {worker_id} ---\n{' '.join(cmd)}\n"
            print(f"[RUN] {country_name} | {worker_id}", flush=True)
            log.write(header)
            log.flush()

            result = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                check=False,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            log.write(f"\nexit={result.returncode}\n")
            log.flush()
            if result.returncode != 0:
                print(
                    f"[FAIL] {country_name} | {worker_id} exit={result.returncode} "
                    f"(see {log_path})",
                    flush=True,
                )
                return result.returncode

    print(f"[DONE] {country_name} -> {out_dir / 'companies.csv'}", flush=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parallel per-country scrape (all catalogs, resume-safe).",
    )
    parser.add_argument(
        "--countries",
        default=None,
        help="Comma-separated countries, e.g. Japan,Indonesia,Singapore",
    )
    parser.add_argument(
        "--all-countries",
        action="store_true",
        help="Run all TARGET_COUNTRIES in parallel pools",
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=int(os.environ.get("G4W_MAX_PARALLEL", "2")),
        help="How many countries to run at once (default 2; recommend 2–3)",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Reset progress.json once per country at start (keeps companies.csv)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Pick countries from a numbered menu",
    )
    return parser.parse_args()


def resolve_countries(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.all_countries:
        return list(config.TARGET_COUNTRIES)
    if args.countries:
        return config.resolve_target_countries(args.countries)
    if args.interactive or sys.stdin.isatty():
        print("\n=== Parallel country runner ===\n")
        print("Tip: max-parallel defaults to 2 (safer vs WAF).\n")
        return config.pick_country_interactive()
    print("Specify --countries, --all-countries, or --interactive", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    args = parse_args()
    max_parallel = max(1, min(args.max_parallel, len(config.TARGET_COUNTRIES)))
    countries = resolve_countries(args)

    # prepare listings once
    prep = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "prepare_listings.py")],
        cwd=str(ROOT),
        check=False,
    )
    if prep.returncode != 0:
        print("prepare_listings failed", file=sys.stderr)
        return prep.returncode

    config.COUNTRIES_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    country_label = (
        countries[0][0] if len(countries) == 1 else f"{len(countries)} countries"
    )
    print("\n--- Summary ---")
    print(f"  Countries    : {', '.join(n for n, _ in countries)}")
    print(f"  Catalogs     : RM → FG → PK → MC (per country)")
    print(f"  Max parallel : {max_parallel}")
    print(f"  Output root  : {config.COUNTRIES_OUTPUT_ROOT}")
    print("  Resume       : yes (per-country progress.json)")
    if sys.stdin.isatty():
        raw = input("\nStart parallel scrape? [Y/n]: ").strip().lower()
        if raw not in ("", "y", "yes"):
            print("Cancelled.")
            return 0

    failures: list[str] = []
    # Thread pool runs country pipelines; each pipeline is sequential workers.
    with ThreadPoolExecutor(max_workers=max_parallel) as pool:
        futures = {
            pool.submit(
                run_one_country,
                name,
                slug,
                reset_progress=args.reset_progress,
            ): name
            for name, slug in countries
        }
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                code = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"[ERROR] {name}: {exc}", flush=True)
                failures.append(name)
                continue
            if code != 0:
                failures.append(name)

    print("\n=== Parallel run finished ===")
    print(f"Output: {config.COUNTRIES_OUTPUT_ROOT}/<country>/companies.csv")
    if failures:
        print(f"Failed countries: {', '.join(failures)}")
        return 1
    print("All countries completed OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
