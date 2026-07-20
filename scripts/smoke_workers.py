#!/usr/bin/env python3
"""Smoke test: prepare listings, offline parsers, then 1 listing per worker."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_script(name: str) -> ModuleType:
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = _load_script("prepare_listings")
g4w_smoke = _load_script("g4w_smoke_test")

WORKERS = prepare.WORKERS
WORKER_IDS = tuple(worker_id.upper() for worker_id, *_ in WORKERS)


def _run_worker_smoke(worker_id: str) -> str:
    """Run one listing for a worker. Returns PASS, PARTIAL, or FAIL."""
    wid = worker_id.lower()
    listings_dir = ROOT / f"listings_{wid}"
    output_dir = ROOT / f"Go4World_{worker_id.upper()}"
    terms = listings_dir / "terms.csv"
    if not terms.exists():
        print(f"FAIL {worker_id}: missing {terms}")
        return "FAIL"

    cmd = [
        sys.executable,
        str(ROOT / "main_go4world.py"),
        "--listings-dir",
        str(listings_dir),
        "--output-dir",
        str(output_dir),
        "--max-listings",
        "1",
        "--country",
        "indonesia",
        "--single-csv",
        "--reset-progress",
        "--fast",
        "--skip-empty-tabs",
    ]
    env = {
        **os.environ,
        "G4W_MAX_PAGES_PER_SEARCH": "1",
        "G4W_MAX_PROFILES_PER_LISTING": "3",
        "G4W_MAX_BUYLEADS_PER_PAGE": "2",
        "G4W_MIN_DELAY": "2.0",
        "G4W_MAX_DELAY": "4.0",
    }
    print(f"\n=== Worker {worker_id} smoke (1 listing × indonesia, capped) ===")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT), check=False, env=env)

    csv_path = output_dir / "companies.csv"
    progress_path = output_dir / "progress.json"

    if result.returncode == 0 and csv_path.exists() and csv_path.stat().st_size > 0:
        print(f"PASS {worker_id}: wrote {csv_path}")
        return "PASS"

    if progress_path.exists() or (csv_path.exists() and csv_path.stat().st_size > 0):
        print(
            f"PARTIAL {worker_id}: scraper ran but may be empty/blocked "
            f"(exit={result.returncode}, csv={csv_path.exists()})"
        )
        return "PARTIAL"

    if result.returncode != 0:
        print(f"PARTIAL {worker_id}: live scrape failed/blocked (exit={result.returncode})")
        return "PARTIAL"

    print(f"FAIL {worker_id}: no output under {output_dir}")
    return "FAIL"


def main() -> int:
    print("Preparing listing folders...")
    prep_code = prepare.main()
    if prep_code != 0:
        print("SMOKE WORKERS: FAIL (prepare_listings)")
        return 1

    print("\nOffline parser checks...")
    parser_ok = g4w_smoke.test_parser_offline()
    saved_ok = g4w_smoke.test_saved_html()
    if not parser_ok:
        print("SMOKE WORKERS: FAIL (offline parser)")
        return 1

    results: dict[str, str] = {}
    for worker_id, *_ in WORKERS:
        results[worker_id.upper()] = _run_worker_smoke(worker_id.upper())

    print("\n=== Smoke workers summary ===")
    for wid in WORKER_IDS:
        print(f"  {wid}: {results[wid]}")

    statuses = set(results.values())
    if statuses == {"PASS"} and saved_ok:
        print("SMOKE WORKERS: FULL PASS")
        return 0
    if "FAIL" in statuses:
        print("SMOKE WORKERS: FAIL")
        return 1
    print(
        "SMOKE WORKERS: PARTIAL PASS — parsers OK; "
        "one or more live workers blocked/empty (use --cdp or proxy for full runs)"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
